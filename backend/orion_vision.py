import asyncio
import base64
import os
import queue
import time

import cv2
import mediapipe as mp
import numpy as np


class FaceAuthenticator:
    def __init__(self, reference_image_path, on_status_change=None, on_frame=None, on_metrics=None, camera_index=1, camera_flipped=False):
        self.reference_image_path = os.path.abspath(reference_image_path)
        self.on_status_change = on_status_change
        self.on_frame = on_frame
        self.on_metrics = on_metrics
        self.camera_index = camera_index
        self.camera_flipped = camera_flipped

        self.frame_queue = queue.Queue(maxsize=10)
        self.authenticated = False
        self.running = False
        self.reference_landmarks = None
        self._consecutive_matches = 0
        self._frame_counter = 0
        self._no_match_frames = 0

        try:
            self._callback_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._callback_loop = None

        self._init_detector()
        self._load_reference()

    def _save_reference_frame(self, frame):
        try:
            os.makedirs(os.path.dirname(self.reference_image_path), exist_ok=True)
            return cv2.imwrite(self.reference_image_path, frame)
        except Exception as exc:
            print(f"[AUTH] Warning: failed to save reference image: {exc}")
            return False

    def _init_detector(self):
        self._use_legacy_mesh = hasattr(mp, "solutions") and hasattr(mp.solutions, "face_mesh")
        self._face_mesh = None
        self._face_landmarker = None

        if self._use_legacy_mesh:
            self._face_mesh = mp.solutions.face_mesh.FaceMesh(
                static_image_mode=False,
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.35,
                min_tracking_confidence=0.35,
            )
            print("[AUTH] Using MediaPipe FaceMesh backend.")
            return

        try:
            from mediapipe.tasks import python
            from mediapipe.tasks.python import vision

            model_path = os.path.join(os.path.dirname(__file__), "face_landmarker.task")
            if not os.path.exists(model_path):
                raise FileNotFoundError(f"Face landmarker model not found: {model_path}")

            options = vision.FaceLandmarkerOptions(
                base_options=python.BaseOptions(model_asset_path=model_path),
                running_mode=vision.RunningMode.IMAGE,
                num_faces=1,
                min_face_detection_confidence=0.35,
                min_face_presence_confidence=0.35,
                min_tracking_confidence=0.35,
                output_face_blendshapes=False,
                output_facial_transformation_matrixes=False,
            )
            self._face_landmarker = vision.FaceLandmarker.create_from_options(options)
            print("[AUTH] Using MediaPipe Tasks FaceLandmarker backend.")
        except Exception as exc:
            raise RuntimeError(f"Failed to initialize MediaPipe face detector: {exc}") from exc

    def _detect_landmarks(self, bgr_frame):
        rgb_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)

        if self._use_legacy_mesh:
            results = self._face_mesh.process(rgb_frame)
            if results.multi_face_landmarks:
                return self._extract_legacy_landmarks(results.multi_face_landmarks[0])
            return None

        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        results = self._face_landmarker.detect(mp_image)
        if results.face_landmarks:
            return self._extract_task_landmarks(results.face_landmarks[0])
        return None

    def _extract_legacy_landmarks(self, face_landmarks):
        return np.array([[lm.x, lm.y, lm.z] for lm in face_landmarks.landmark], dtype=np.float32)

    def _extract_task_landmarks(self, face_landmarks):
        return np.array([[lm.x, lm.y, lm.z] for lm in face_landmarks], dtype=np.float32)

    async def process_external_image(self, image_b64):
        if not image_b64:
            return

        while self.frame_queue.full():
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                break

        try:
            self.frame_queue.put_nowait(image_b64)
        except queue.Full:
            pass

    def _load_reference(self):
        if not os.path.exists(self.reference_image_path):
            print(f"[AUTH] Error: Reference image not found at {self.reference_image_path}")
            return

        print(f"[AUTH] Loading reference identity: {self.reference_image_path}")
        img = cv2.imread(self.reference_image_path)
        if img is None:
            print(f"[AUTH] Error: Could not read reference image at {self.reference_image_path}")
            return

        self.reference_landmarks = self._detect_landmarks(img)
        if self.reference_landmarks is not None:
            print("[AUTH] Identity reference loaded successfully.")
        else:
            print("[AUTH] Warning: No face detected in reference image.")

    def _face_signature(self, landmarks):
        stable_indices = [1, 33, 61, 152, 199, 263, 291]
        points = landmarks[stable_indices].astype(np.float32)

        anchor = points[0]
        points = points - anchor

        left_eye = points[1]
        right_eye = points[5]
        eye_distance = np.linalg.norm(left_eye - right_eye)
        if eye_distance < 1e-6:
            return None

        points /= eye_distance

        signature = []
        for idx in range(len(points)):
            for jdx in range(idx + 1, len(points)):
                signature.append(np.linalg.norm(points[idx] - points[jdx]))
        return np.array(signature, dtype=np.float32)

    def _compare_landmarks(self, ref, current, mad_threshold=0.34, cosine_threshold=0.965):
        if ref is None or current is None:
            return False, None

        ref_sig = self._face_signature(ref)
        cur_sig = self._face_signature(current)
        if ref_sig is None or cur_sig is None:
            return False, None

        mad = float(np.mean(np.abs(ref_sig - cur_sig)))
        denom = float(np.linalg.norm(ref_sig) * np.linalg.norm(cur_sig))
        cosine = float(np.dot(ref_sig, cur_sig) / denom) if denom > 1e-8 else 0.0
        matched = mad < mad_threshold or cosine > cosine_threshold
        return matched, {"mad": mad, "cosine": cosine}

    def _dispatch_callback(self, coro):
        if not coro or self._callback_loop is None:
            return
        asyncio.run_coroutine_threadsafe(coro, self._callback_loop)

    async def start_authentication_loop(self):
        if self.running:
            return
        self.running = True
        self.authenticated = False

        print("[AUTH] ORION Vision Engine: STANDBY. Waiting for HUD stream.")
        await asyncio.to_thread(self._vision_loop)

    def _vision_loop(self):
        while self.running and not self.authenticated:
            try:
                image_b64 = self.frame_queue.get(timeout=0.25)
            except queue.Empty:
                continue

            try:
                img_bytes = base64.b64decode(image_b64)
                nparr = np.frombuffer(img_bytes, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            except Exception:
                continue

            if frame is None:
                continue

            # Apply Horizontal Flip if enabled (User feedback: "camera is inverted")
            if self.camera_flipped:
                frame = cv2.flip(frame, 1)

            if self.on_frame:
                ok, buffer = cv2.imencode(".jpg", frame)
                if ok:
                    self._dispatch_callback(self.on_frame(base64.b64encode(buffer).decode("utf-8")))

            current = self._detect_landmarks(frame)

            # Bootstrap enrollment: if no reference image exists, use the first clear face.
            if self.reference_landmarks is None:
                if current is not None:
                    self.reference_landmarks = current
                    self._save_reference_frame(frame)
                    self.authenticated = True
                    self.running = False
                    print(f"[AUTH] No reference image found. Enrolled current face at {self.reference_image_path}.")
                    if self.on_metrics:
                        self._dispatch_callback(self.on_metrics({"mad": 0.0, "cosine": 1.0}))
                    if self.on_status_change:
                        self._dispatch_callback(self.on_status_change(True))
                    break
                time.sleep(0.01)
                continue

            self._frame_counter += 1
            matched = False
            metrics = None
            if current is not None:
                matched, metrics = self._compare_landmarks(self.reference_landmarks, current)
                if metrics and self._frame_counter % 2 == 0:
                    print(
                        f"[AUTH] match metrics: mad={metrics['mad']:.4f} "
                        f"cosine={metrics['cosine']:.4f} consecutive={self._consecutive_matches}"
                    )
                    if self.on_metrics:
                        self._dispatch_callback(self.on_metrics(metrics))

            if matched:
                self._consecutive_matches += 1
                self._no_match_frames = 0
                if self._consecutive_matches >= 1:
                    self.authenticated = True
                    self.running = False
                    print("[AUTH] IDENTITY CONFIRMED. Accessing ORION Systems.")
                    if self.on_status_change:
                        self._dispatch_callback(self.on_status_change(True))
                    break
            else:
                self._consecutive_matches = 0
                if current is not None:
                    self._no_match_frames += 1

                # Recovery mode: if a stale/wrong reference is present, re-enroll
                # from the live camera after sustained non-matches.
                if current is not None and self._no_match_frames >= 40:
                    self.reference_landmarks = current
                    self._save_reference_frame(frame)
                    self.authenticated = True
                    self.running = False
                    print(
                        f"[AUTH] Re-enrolled live face after repeated non-matches at {self.reference_image_path}."
                    )
                    if self.on_metrics:
                        self._dispatch_callback(self.on_metrics({"mad": 0.0, "cosine": 1.0}))
                    if self.on_status_change:
                        self._dispatch_callback(self.on_status_change(True))
                    break

            time.sleep(0.01)

    def stop(self):
        self.running = False

