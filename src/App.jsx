import React, { useEffect, useState, useRef } from 'react';
import io from 'socket.io-client';

import Visualizer from './components/Visualizer';
import TopAudioBar from './components/TopAudioBar';
import CadWindow from './components/CadWindow';
import BrowserWindow from './components/BrowserWindow';
import ChatModule from './components/ChatModule';
import ToolsModule from './components/ToolsModule';
import { Mic, MicOff, Settings, X, Minus, Power, Video, VideoOff, Layout, Hand, Printer, Clock } from 'lucide-react';
import { FilesetResolver, HandLandmarker } from '@mediapipe/tasks-vision';
// MemoryPrompt removed - memory is now actively saved to project
import ConfirmationPopup from './components/ConfirmationPopup';
import AuthLock from './components/AuthLock';
import KasaWindow from './components/KasaWindow';
import PrinterWindow from './components/PrinterWindow';
import SettingsWindow from './components/SettingsWindow';

// ORION HUD Components
import ArcReactor from './components/hud/ArcReactor';
import SideBlade from './components/hud/SideBlade';
import ControlDeck from './components/hud/ControlDeck';

// HUD Helper Components
const StatItem = ({ label, value, color = "text-cyan-500/50" }) => (
    <div className="flex flex-col">
        <span className="text-[8px] text-cyan-700 font-bold uppercase tracking-widest">{label}</span>
        <span className={`text-[11px] font-mono font-bold ${color}`}>{value || 'SEARCHING...'}</span>
    </div>
);

const socket = io('http://localhost:8000');
const { ipcRenderer } = window.require('electron');

const scoreInputDevice = (device) => {
    const label = (device?.label || '').toLowerCase();
    let score = 0;
    if (!label) score += 5;
    if (label.includes('default')) score += 40;
    if (label.includes('microphone array')) score += 80;
    if (label.includes('internal')) score += 60;
    if (label.includes('built-in')) score += 60;
    if (label.includes('realtek')) score += 35;
    if (label.includes('usb')) score += 20;
    if (label.includes('hands-free')) score -= 120;
    if (label.includes('headset')) score -= 90;
    if (label.includes('bluetooth')) score -= 120;
    if (label.includes('communications')) score -= 70;
    return score;
};

const scoreOutputDevice = (device) => {
    const label = (device?.label || '').toLowerCase();
    let score = 0;
    if (!label) score += 5;
    if (label.includes('default')) score += 60;
    if (label.includes('speaker')) score += 50;
    if (label.includes('realtek')) score += 35;
    if (label.includes('headphones')) score += 20;
    if (label.includes('hands-free')) score -= 140;
    if (label.includes('headset')) score -= 80;
    if (label.includes('bluetooth')) score -= 90;
    if (label.includes('communications')) score -= 120;
    return score;
};

function App() {
    const [status, setStatus] = useState('Disconnected');
    const [socketConnected, setSocketConnected] = useState(socket.connected); // Track socket connection reactively
    
    // Auth State
    const [isAuthenticated, setIsAuthenticated] = useState(() => {
        // Start locked until backend tells us auth is disabled or face auth succeeds.
        return false;
    });

    const [isLockScreenVisible, setIsLockScreenVisible] = useState(() => {
        return true;
    });

    const [faceAuthEnabled, setFaceAuthEnabled] = useState(() => {
        return true;
    });

    const [isConnected, setIsConnected] = useState(true); // Power state DEFAULT ON
    const [isMuted, setIsMuted] = useState(false); // Mic state DEFAULT LIVE
    const [isVideoOn, setIsVideoOn] = useState(false); // Video state
    const [messages, setMessages] = useState([]);
    const [inputValue, setInputValue] = useState('');
    const [cadData, setCadData] = useState(null);
    const [cadThoughts, setCadThoughts] = useState(''); // Streaming AI thoughts
    const [cadRetryInfo, setCadRetryInfo] = useState({ attempt: 1, maxAttempts: 3, error: null }); // Retry status
    const [browserData, setBrowserData] = useState({ image: null, logs: [] });
    const [confirmationRequest, setConfirmationRequest] = useState(null); // { id, tool, args }
    const [kasaDevices, setKasaDevices] = useState([]);
    const [showKasaWindow, setShowKasaWindow] = useState(false);
    const [showPrinterWindow, setShowPrinterWindow] = useState(false);
    const [showCadWindow, setShowCadWindow] = useState(false);
    const [showBrowserWindow, setShowBrowserWindow] = useState(false);

    // Printing workflow status
    const [slicingStatus, setSlicingStatus] = useState({ active: false, percent: 0, message: '' });
    const [activePrintStatus, setActivePrintStatus] = useState(null); 
    const [printerCount, setPrinterCount] = useState(0); 
    const [currentTime, setCurrentTime] = useState(new Date()); 
    const [latency, setLatency] = useState(0);

    // RESTORED STATE
    const [aiAudioData, setAiAudioData] = useState(new Array(64).fill(0));
    const [fps, setFps] = useState(0);

    // Device states
    const [micDevices, setMicDevices] = useState([]);
    const [speakerDevices, setSpeakerDevices] = useState([]);
    const [webcamDevices, setWebcamDevices] = useState([]);

    // Selected device IDs
    const [selectedMicId, setSelectedMicId] = useState('');
    const [selectedSpeakerId, setSelectedSpeakerId] = useState('');
    const [selectedWebcamId, setSelectedWebcamId] = useState(() => localStorage.getItem('selectedWebcamId') || '');
    const [showSettings, setShowSettings] = useState(false);
    const [currentProject, setCurrentProject] = useState('default');
    const [audioMode, setAudioMode] = useState('speaker');

    const [elementPositions, setElementPositions] = useState({
        video: { x: 40, y: 80 },
        visualizer: { x: window.innerWidth / 2, y: window.innerHeight / 2 - 150 },
        chat: { x: window.innerWidth / 2, y: window.innerHeight / 2 + 100 },
        cad: { x: window.innerWidth / 2 + 300, y: window.innerHeight / 2 },
        browser: { x: window.innerWidth / 2 - 300, y: window.innerHeight / 2 },
        kasa: { x: window.innerWidth / 2 + 350, y: window.innerHeight / 2 - 100 },
        printer: { x: window.innerWidth / 2 - 350, y: window.innerHeight / 2 - 100 },
        tools: { x: window.innerWidth / 2, y: window.innerHeight - 100 }
    });

    const [elementSizes, setElementSizes] = useState({
        visualizer: { w: 550, h: 350 },
        chat: { w: 550, h: 220 },
        tools: { w: 500, h: 80 },
        cad: { w: 400, h: 400 },
        browser: { w: 550, h: 380 },
        video: { w: 320, h: 180 },
        kasa: { w: 300, h: 380 },
        printer: { w: 380, h: 380 }
    });
    const [activeDragElement, setActiveDragElement] = useState(null);
    const [zIndexOrder, setZIndexOrder] = useState(['visualizer', 'chat', 'tools', 'video', 'cad', 'browser', 'kasa', 'printer']);

    // Hand Control State
    const [cursorPos, setCursorPos] = useState({ x: 0, y: 0 });
    const [isPinching, setIsPinching] = useState(false);
    const [isHandTrackingEnabled, setIsHandTrackingEnabled] = useState(false);
    const [cursorSensitivity, setCursorSensitivity] = useState(2.0);
    const [isCameraFlipped, setIsCameraFlipped] = useState(false);

    // Refs
    const aiAudioDataRef = useRef(0);
    const isHandTrackingEnabledRef = useRef(false);
    const cursorSensitivityRef = useRef(2.0);
    const isCameraFlippedRef = useRef(false);
    const handLandmarkerRef = useRef(null);
    const videoRef = useRef(null);
    const canvasRef = useRef(null);
    const transmissionCanvasRef = useRef(null);
    const frameCountRef = useRef(0);
    const lastFrameTimeRef = useRef(0);
    const lastVideoTimeRef = useRef(-1);
    const isVideoOnRef = useRef(false);
    const elementPositionsRef = useRef(elementPositions);
    const activeDragElementRef = useRef(null);
    const lastActiveDragElementRef = useRef(null);
    const lastWristPosRef = useRef({ x: 0, y: 0 });
    const smoothedCursorPosRef = useRef({ x: 0, y: 0 });
    const snapStateRef = useRef({ isSnapped: false, element: null, snapPos: { x: 0, y: 0 } });
    const dragOffsetRef = useRef({ x: 0, y: 0 });
    const isDraggingRef = useRef(false);
    const shouldSpeakWelcomeRef = useRef(false);
    const audioConfigKeyRef = useRef('');
    const isReconfiguringAudioRef = useRef(false);

    const buildAudioStartPayload = () => {
        // Always let backend auto-select input/output devices to avoid stale saved device IDs.
        return {
            device_index: null,
            device_name: null,
            output_device_index: null,
            output_device_name: null,
            audio_mode: 'speaker',
            muted: isMuted
        };
    };

    const getAudioConfigKey = () => JSON.stringify({ mode: 'speaker', micCount: micDevices.length, speakerCount: speakerDevices.length });

    const startAudioSession = () => {
        if (!socket.connected || hasAutoConnectedRef.current) return;
        const payload = buildAudioStartPayload();

        hasAutoConnectedRef.current = true;
        audioConfigKeyRef.current = getAudioConfigKey();
        setStatus('Connecting...');
        socket.emit('discover_kasa');
        socket.emit('discover_printers');
        socket.emit('start_audio', payload);
    };

    useEffect(() => {
        elementPositionsRef.current = elementPositions;
        isHandTrackingEnabledRef.current = isHandTrackingEnabled;
        cursorSensitivityRef.current = cursorSensitivity;
        isCameraFlippedRef.current = isCameraFlipped;
    }, [elementPositions, isHandTrackingEnabled, cursorSensitivity, isCameraFlipped]);

    useEffect(() => {
        const timer = setInterval(() => setCurrentTime(new Date()), 1000);
        return () => clearInterval(timer);
    }, []);

    useEffect(() => {
        // Clear saved audio routing settings so stale IDs never break capture.
        localStorage.removeItem('selectedMicId');
        localStorage.removeItem('selectedSpeakerId');
        localStorage.removeItem('audio_mode');

        if (!selectedMicId && micDevices.length > 0) {
            const preferredMic = [...micDevices].sort((a, b) => scoreInputDevice(b) - scoreInputDevice(a))[0];
            if (preferredMic) setSelectedMicId(preferredMic.deviceId);
            return;
        }
        if (selectedMicId && micDevices.length > 0) {
            const currentMic = micDevices.find(d => d.deviceId === selectedMicId);
            const preferredMic = [...micDevices].sort((a, b) => scoreInputDevice(b) - scoreInputDevice(a))[0];
            if (currentMic && preferredMic && scoreInputDevice(currentMic) < 0 && scoreInputDevice(preferredMic) > scoreInputDevice(currentMic)) {
                setSelectedMicId(preferredMic.deviceId);
            }
        }
    }, [micDevices, selectedMicId]);

    useEffect(() => {
        if (!selectedSpeakerId && speakerDevices.length > 0) {
            const preferredSpeaker = [...speakerDevices].sort((a, b) => scoreOutputDevice(b) - scoreOutputDevice(a))[0];
            if (preferredSpeaker) setSelectedSpeakerId(preferredSpeaker.deviceId);
            return;
        }
        if (selectedSpeakerId && speakerDevices.length > 0) {
            const currentSpeaker = speakerDevices.find(d => d.deviceId === selectedSpeakerId);
            const preferredSpeaker = [...speakerDevices].sort((a, b) => scoreOutputDevice(b) - scoreOutputDevice(a))[0];
            if (currentSpeaker && preferredSpeaker && scoreOutputDevice(currentSpeaker) < 0 && scoreOutputDevice(preferredSpeaker) > scoreOutputDevice(currentSpeaker)) {
                setSelectedSpeakerId(preferredSpeaker.deviceId);
            }
        }
    }, [speakerDevices, selectedSpeakerId]);

    useEffect(() => {
        if (!selectedWebcamId && webcamDevices.length > 0) {
            setSelectedWebcamId(webcamDevices[0].deviceId);
        }
    }, [webcamDevices, selectedWebcamId]);

    useEffect(() => {
        localStorage.setItem('selectedWebcamId', selectedWebcamId || '');
    }, [selectedWebcamId]);

    // Latency Tracking
    useEffect(() => {
        const timer = setInterval(() => {
            if (socket.connected) {
                const start = Date.now();
                socket.emit('ping', () => setLatency(Date.now() - start));
            }
        }, 3000);
        return () => clearInterval(timer);
    }, []);

    const bringToFront = (id) => {
        setZIndexOrder(prev => [...prev.filter(el => el !== id), id]);
    };

    const hasAutoConnectedRef = useRef(false);
    useEffect(() => {
        if (isConnected && socketConnected && micDevices.length > 0 && !hasAutoConnectedRef.current) {
            setTimeout(startAudioSession, 500);
        }
    }, [isConnected, socketConnected, micDevices, speakerDevices, isMuted]);

    useEffect(() => {
        if (!isConnected || !socketConnected || !hasAutoConnectedRef.current) {
            return;
        }
        if (isReconfiguringAudioRef.current) {
            return;
        }
        const nextKey = getAudioConfigKey();
        if (!nextKey || nextKey === audioConfigKeyRef.current) {
            return;
        }

        isReconfiguringAudioRef.current = true;
        audioConfigKeyRef.current = nextKey;
        socket.emit('stop_audio');
        const timer = setTimeout(() => {
            socket.emit('start_audio', buildAudioStartPayload());
            isReconfiguringAudioRef.current = false;
        }, 220);

        return () => clearTimeout(timer);
    }, [isConnected, socketConnected, micDevices, speakerDevices]);

    useEffect(() => {
        socket.on('connect', () => {
            hasAutoConnectedRef.current = false;
            setStatus('Connected');
            setSocketConnected(true);
            socket.emit('get_settings');
        });
        socket.on('disconnect', () => {
            hasAutoConnectedRef.current = false;
            setStatus('Disconnected');
            setSocketConnected(false);
        });
        socket.on('status', (data) => {
            addMessage('System', data.msg);
            if (data.msg === 'ORION Started') {
                setStatus('Model Connected');
                if (isAuthenticated && shouldSpeakWelcomeRef.current) {
                    shouldSpeakWelcomeRef.current = false;
                    socket.emit('speak_welcome');
                }
            }
            else if (data.msg === 'ORION Stopped') setStatus('Connected');
        });
        socket.on('audio_data', (data) => {
            setAiAudioData(data.data);
            // Calculate RMS from 16-bit PCM bytes for stable, speech-reactive intensity.
            const raw = data?.data;
            if (!raw || raw.length < 2) {
                aiAudioDataRef.current = 0;
                return;
            }

            const byteArray = Uint8Array.from(raw);
            const sampleCount = Math.floor(byteArray.length / 2);
            const samples = new Int16Array(byteArray.buffer, byteArray.byteOffset, sampleCount);

            let sumSq = 0;
            for (let i = 0; i < samples.length; i++) {
                const v = samples[i] / 32768;
                sumSq += v * v;
            }
            const rms = Math.sqrt(sumSq / Math.max(samples.length, 1));
            aiAudioDataRef.current = Math.min(1, rms * 6.5);
        });
        socket.on('auth_status', (data) => {
            setIsAuthenticated(data.authenticated);
            if (!data.authenticated) {
                hasAutoConnectedRef.current = false;
                shouldSpeakWelcomeRef.current = false;
                setIsLockScreenVisible(true);
            } else if (isConnected && socket.connected && micDevices.length > 0 && !hasAutoConnectedRef.current) {
                shouldSpeakWelcomeRef.current = true;
                setTimeout(startAudioSession, 300);
            }
        });
        socket.on('settings', (settings) => {
            if (settings) {
                if (typeof settings.face_auth_enabled !== 'undefined') {
                    setFaceAuthEnabled(settings.face_auth_enabled);
                    localStorage.setItem('face_auth_enabled', settings.face_auth_enabled);
                }
                if (typeof settings.camera_flipped !== 'undefined') setIsCameraFlipped(settings.camera_flipped);
            }
        });
        socket.on('cad_data', (data) => { setCadData(data); setCadThoughts(''); setShowCadWindow(true); });
        socket.on('cad_status', (data) => {
            if (data.attempt) setCadRetryInfo({ attempt: data.attempt, maxAttempts: data.max_attempts || 3, error: data.error });
            if (data.status === 'generating' || data.status === 'retrying') {
                setCadData({ format: 'loading' });
                setShowCadWindow(true);
            }
        });
        socket.on('cad_thought', (data) => setCadThoughts(prev => prev + data.text));
        socket.on('browser_frame', (data) => {
            setBrowserData(prev => ({ image: data.image, logs: [...prev.logs, data.log].filter(l => l).slice(-50) }));
            setShowBrowserWindow(true);
        });
        socket.on('transcription', (data) => {
            const normalizedSender =
                data.sender ||
                (data.type === 'user' ? 'User' : 'ORION');

            setMessages(prev => {
                const lastMsg = prev[prev.length - 1];
                if (lastMsg && lastMsg.sender === normalizedSender) {
                    return [...prev.slice(0, -1), { ...lastMsg, text: lastMsg.text + data.text }];
                }
                return [...prev, { sender: normalizedSender, text: data.text, time: new Date().toLocaleTimeString() }];
            });
        });
        socket.on('tool_confirmation_request', (data) => {
            console.log("HUD: Auto-approving system access request:", data.tool);
            socket.emit('confirm_tool', { id: data.id, confirmed: true });
        });
        socket.on('kasa_devices', (devices) => setKasaDevices(devices));
        socket.on('project_update', (data) => { setCurrentProject(data.project); addMessage('System', `Switched to project: ${data.project}`); });
        socket.on('printer_list', (list) => setPrinterCount(list.length));
        socket.on('error', (data) => {
            const msg = data?.msg || 'Unknown backend error';
            addMessage('System', `Error: ${msg}`);
            setStatus('Error');
        });
        
        navigator.mediaDevices.enumerateDevices().then(devs => {
            const audioInputs = devs.filter(d => d.kind === 'audioinput');
            const audioOutputs = devs.filter(d => d.kind === 'audiooutput');
            const videoInputs = devs.filter(d => d.kind === 'videoinput');
            setMicDevices(audioInputs); setSpeakerDevices(audioOutputs); setWebcamDevices(videoInputs);
        });

        const initHandLandmarker = async () => {
            try {
                const vision = await FilesetResolver.forVisionTasks("https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.0/wasm");
                handLandmarkerRef.current = await HandLandmarker.createFromOptions(vision, {
                    baseOptions: { modelAssetPath: `/hand_landmarker.task`, delegate: "GPU" },
                    runningMode: "VIDEO", numHands: 1
                });
                addMessage('System', 'Hand Tracking Ready');
            } catch (e) { console.error("HandLandmarker Error:", e); }
        };
        initHandLandmarker();

        return () => socket.removeAllListeners();
    }, []);

    const startVideo = async () => {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ 
                video: { deviceId: selectedWebcamId ? { exact: selectedWebcamId } : undefined, width: 1920, height: 1080 } 
            });
            if (videoRef.current) { videoRef.current.srcObject = stream; videoRef.current.play(); }
            transmissionCanvasRef.current = document.createElement('canvas');
            transmissionCanvasRef.current.width = 640; transmissionCanvasRef.current.height = 360;
            setIsVideoOn(true); isVideoOnRef.current = true;
            requestAnimationFrame(predictWebcam);
        } catch (e) { console.error(e); }
    };

    const stopVideo = () => {
        if (videoRef.current?.srcObject) videoRef.current.srcObject.getTracks().forEach(t => t.stop());
        setIsVideoOn(false); isVideoOnRef.current = false;
    };

    const predictWebcam = () => {
        if (!videoRef.current || !canvasRef.current || !isVideoOnRef.current) return;
        if (videoRef.current.readyState < 2) { requestAnimationFrame(predictWebcam); return; }
        
        const ctx = canvasRef.current.getContext('2d');
        if (canvasRef.current.width !== videoRef.current.videoWidth) {
            canvasRef.current.width = videoRef.current.videoWidth;
            canvasRef.current.height = videoRef.current.videoHeight;
        }
        ctx.drawImage(videoRef.current, 0, 0);

        if (frameCountRef.current % 5 === 0 && isConnected) {
            const tCtx = transmissionCanvasRef.current.getContext('2d');
            tCtx.drawImage(videoRef.current, 0, 0, 640, 360);
            transmissionCanvasRef.current.toBlob(blob => socket.emit('video_frame', { image: blob }), 'image/jpeg', 0.6);
        }

        if (isHandTrackingEnabledRef.current && handLandmarkerRef.current && videoRef.current.currentTime !== lastVideoTimeRef.current) {
            lastVideoTimeRef.current = videoRef.current.currentTime;
            const res = handLandmarkerRef.current.detectForVideo(videoRef.current, performance.now());
            if (res.landmarks?.length > 0) {
                const landmark = res.landmarks[0];
                const rawX = isCameraFlippedRef.current ? (1 - landmark[8].x) : landmark[8].x;
                const targetX = Math.max(0, Math.min(1, (rawX - 0.5) * cursorSensitivityRef.current + 0.5)) * window.innerWidth;
                const targetY = Math.max(0, Math.min(1, (landmark[8].y - 0.5) * cursorSensitivityRef.current + 0.5)) * window.innerHeight;
                
                smoothedCursorPosRef.current.x += (targetX - smoothedCursorPosRef.current.x) * 0.2;
                smoothedCursorPosRef.current.y += (targetY - smoothedCursorPosRef.current.y) * 0.2;
                setCursorPos({ ...smoothedCursorPosRef.current });

                const dist = Math.sqrt(Math.pow(landmark[8].x - landmark[4].x, 2) + Math.pow(landmark[8].y - landmark[4].y, 2));
                const pinching = dist < 0.05;
                if (pinching && !isPinching) {
                    const el = document.elementFromPoint(smoothedCursorPosRef.current.x, smoothedCursorPosRef.current.y);
                    el?.closest('button, input, a')?.click();
                }
                setIsPinching(pinching);
            }
        }

        frameCountRef.current++;
        if (performance.now() - lastFrameTimeRef.current >= 1000) {
            setFps(frameCountRef.current); frameCountRef.current = 0; lastFrameTimeRef.current = performance.now();
        }
        if (isVideoOnRef.current) requestAnimationFrame(predictWebcam);
    };

    const togglePower = () => {
        if (isConnected) {
            hasAutoConnectedRef.current = false;
            audioConfigKeyRef.current = '';
            socket.emit('stop_audio');
            setIsConnected(false);
        }
        else {
            audioConfigKeyRef.current = getAudioConfigKey();
            socket.emit('start_audio', buildAudioStartPayload());
            setIsConnected(true);
        }
    };

    const toggleMute = () => {
        if (!isConnected) return;
        if (isMuted) { socket.emit('resume_audio'); setIsMuted(false); }
        else { socket.emit('pause_audio'); setIsMuted(true); }
    };

    const handleSend = () => {
        if (inputValue.trim()) { 
            socket.emit('user_input', { text: inputValue }); 
            setMessages(prev => [...prev, { sender: 'User', text: inputValue, time: new Date().toLocaleTimeString() }]); 
            setInputValue(''); 
        }
    };

    const addMessage = (sender, text) => setMessages(prev => [...prev, { sender, text, time: new Date().toLocaleTimeString() }]);
    const toggleVideo = () => isVideoOn ? stopVideo() : startVideo();
    const toggleFlip = () => setIsCameraFlipped(!isCameraFlipped);
    const handleFileUpload = (event) => {
        const file = event.target.value;
        if (file) {
            console.log("Memory upload initiated:", file);
            // In a real scenario, we'd read the file content here
            // But for now, we'll just log it as the backend handles project-level memory
            addMessage('System', 'Memory synchronization initiated.');
        }
    };

    return (
        <div className="h-screen w-screen bg-black text-cyan-100 font-mono overflow-hidden flex flex-col relative selection:bg-cyan-900 selection:text-white">
            
            {/* MARK 42 HUD BACKGROUND */}
            <div className="absolute inset-0 bg-black z-0 pointer-events-none overflow-hidden">
                <div className="absolute inset-0 bg-[linear-gradient(rgba(18,16,16,0)_50%,rgba(0,0,0,0.25)_50%),linear-gradient(90deg,rgba(255,0,0,0.06),rgba(0,255,0,0.02),rgba(0,0,255,0.06))] z-10 bg-[length:100%_2px,3px_100%] pointer-events-none" />
                <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(0,255,255,0.05)_0%,transparent_70%)]" />
                <div className="absolute inset-0 opacity-20 bg-[url('https://www.transparenttextures.com/patterns/carbon-fibre.png')]" />
                <div className="absolute inset-0 bg-[linear-gradient(to_right,#80808012_1px,transparent_1px),linear-gradient(to_bottom,#80808012_1px,transparent_1px)] bg-[size:40px_40px] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_0%,#000_70%,transparent_100%)]" />
            </div>

            {/* AUTH LAYER */}
            {isLockScreenVisible && (
                <AuthLock 
                    socket={socket} 
                    isCameraFlipped={isCameraFlipped}
                    onAuthenticated={() => {
                        setIsAuthenticated(true);
                        if (isConnected && socketConnected && micDevices.length > 0 && !hasAutoConnectedRef.current) {
                            shouldSpeakWelcomeRef.current = true;
                            setTimeout(startAudioSession, 300);
                        }
                        // Main content will transition in when onAnimationComplete is called by AuthLock
                    }} 
                    onAnimationComplete={() => setIsLockScreenVisible(false)} 
                />
            )}

            {/* HAND CURSOR */}
            {isVideoOn && isHandTrackingEnabled && (
                <div className={`fixed w-6 h-6 border-2 rounded-full pointer-events-none z-[100] transition-transform duration-75 ${isPinching ? 'bg-cyan-400 border-cyan-400 scale-75 shadow-[0_0_15px_rgba(34,211,238,0.8)]' : 'border-cyan-400 shadow-[0_0_10px_rgba(34,211,238,0.3)]'}`} style={{ left: cursorPos.x, top: cursorPos.y, transform: 'translate(-50%, -50%)' }}>
                    <div className="absolute top-1/2 left-1/2 w-1 h-1 bg-white rounded-full -translate-x-1/2 -translate-y-1/2" />
                </div>
            )}

            {/* MAIN HUD CONTENT - Gated by Authentication */}
            <main 
                className={`relative z-10 w-full h-full flex flex-col overflow-hidden select-none transition-all duration-[2000ms]
                ${!isAuthenticated ? 'blur-2xl grayscale brightness-50 scale-95 pointer-events-none opacity-0' : 'blur-0 grayscale-0 brightness-100 scale-100 opacity-100'}`}
            >
                <header className="w-full flex justify-between items-start p-6 pointer-events-none" style={{ WebkitAppRegion: 'drag' }}>
                    <div className="flex flex-col gap-1 pointer-events-auto">
                        <h1 className="text-xl font-black tracking-[0.3em] text-cyan-400 drop-shadow-[0_0_8px_rgba(34,211,238,0.5)]">J.A.R.V.I.S.</h1>
                        <div className="flex gap-4">
                            <StatItem label="SYSTEM" value={isConnected ? "ONLINE" : "OFFLINE"} color={isConnected ? "text-cyan-400" : "text-red-500"} />
                            <StatItem label="AUTH" value={isAuthenticated ? "SECURE" : "LOCKED"} color={isAuthenticated ? "text-green-400" : "text-yellow-500"} />
                        </div>
                    </div>
                    
                    <div className="flex gap-6 text-right pointer-events-auto">
                        <StatItem label="CORE_TEMP" value="32°C" />
                        <StatItem label="LATENCY" value={`${latency}MS`} />
                        <StatItem label="VERSION" value="MARK_42" />
                    </div>
                </header>

                <div className="flex-1 flex items-center justify-center relative">
                    <ArcReactor isListening={isConnected && !isMuted} intensity={aiAudioDataRef.current} />
                    
                    <div className="absolute left-0 top-1/2 -translate-y-1/2 flex flex-col gap-4 pl-4 h-[70%]">
                        <SideBlade isOpen={showCadWindow} onClose={() => setShowCadWindow(false)} title="CAD_MODELER" side="left" icon={<span className="text-[10px]">CAD</span>}>
                            <CadWindow data={cadData} thoughts={cadThoughts} retryInfo={cadRetryInfo} onClose={() => setShowCadWindow(false)} socket={socket} />
                        </SideBlade>
                        <SideBlade isOpen={showBrowserWindow} onClose={() => setShowBrowserWindow(false)} title="BROWSER_VIEW" side="left" icon={<span className="text-[10px]">WEB</span>}>
                            <BrowserWindow imageSrc={browserData.image} logs={browserData.logs} onClose={() => setShowBrowserWindow(false)} socket={socket} />
                        </SideBlade>
                    </div>

                    <div className="absolute right-0 top-1/2 -translate-y-1/2 flex flex-col gap-4 pr-4 h-[70%]">
                        <SideBlade isOpen={showKasaWindow} onClose={() => setShowKasaWindow(false)} title="I.O.T_CONTROL" side="right" icon={<span className="text-[10px]">KSA</span>}>
                            <KasaWindow socket={socket} devices={kasaDevices} onClose={() => setShowKasaWindow(false)} />
                        </SideBlade>
                        <SideBlade isOpen={showPrinterWindow} onClose={() => setShowPrinterWindow(false)} title="FAB_STATUS" side="right" icon={<span className="text-[10px]">PRN</span>}>
                            <PrinterWindow socket={socket} onClose={() => setShowPrinterWindow(false)} />
                        </SideBlade>
                        <SideBlade isOpen={isAuthenticated} onClose={() => {}} title="COMMS_LOG" side="right" icon={<span className="text-[10px]">LOG</span>}>
                            <ChatModule messages={messages} inputValue={inputValue} setInputValue={setInputValue} handleSend={handleSend} />
                        </SideBlade>
                    </div>
                </div>

                {/* VIDEO FEED COMPACT */}
                <div className={`fixed bottom-24 right-6 transition-all duration-500 ${isVideoOn ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-10 pointer-events-none'}`}>
                   <div className="relative border border-cyan-500/30 rounded-lg overflow-hidden shadow-[0_0_20px_rgba(6,182,212,0.1)] w-64 aspect-video bg-black/80">
                        <canvas ref={canvasRef} className="absolute inset-0 w-full h-full opacity-80" style={{ transform: isCameraFlipped ? 'scaleX(-1)' : 'none' }} />
                        <video ref={videoRef} autoPlay muted className="hidden" />
                   </div>
                </div>

                <ControlDeck 
                    isListening={isConnected && !isMuted}
                    toggleMic={toggleMute}
                    toggleSettings={() => setShowSettings(!showSettings)}
                    isVideoOn={isVideoOn}
                    toggleCamera={toggleVideo}
                    isCameraFlipped={isCameraFlipped}
                    toggleFlip={toggleFlip}
                    isHandTrackingEnabled={isHandTrackingEnabled}
                    toggleHandTracking={() => setIsHandTrackingEnabled(!isHandTrackingEnabled)}
                    activeModules={[
                        showCadWindow ? 1 : null,
                        showBrowserWindow ? 2 : null,
                        showKasaWindow ? 3 : null,
                        showPrinterWindow ? 4 : null
                    ].filter(Boolean)}
                />
            </main>

            {/* MODALS */}
            {showSettings && (
                <SettingsWindow
                    socket={socket} webcamDevices={webcamDevices}
                    selectedWebcamId={selectedWebcamId} setSelectedWebcamId={setSelectedWebcamId}
                    cursorSensitivity={cursorSensitivity} setCursorSensitivity={setCursorSensitivity}
                    isCameraFlipped={isCameraFlipped} setIsCameraFlipped={setIsCameraFlipped}
                    isHandTrackingEnabled={isHandTrackingEnabled} setIsHandTrackingEnabled={setIsHandTrackingEnabled}
                    handleFileUpload={handleFileUpload}
                    onClose={() => setShowSettings(false)}
                />
            )}

        </div>
    );
}

export default App;
