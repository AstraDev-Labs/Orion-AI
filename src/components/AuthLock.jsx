import React, { useEffect, useRef, useState } from 'react';
import { Lock, Unlock, User, ShieldCheck, Activity, Cpu } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

const AuthLock = ({ socket, isCameraFlipped, onAuthenticated, onAnimationComplete }) => {
    const videoPreviewRef = useRef(null);
    const captureCanvasRef = useRef(null);
    const onAuthenticatedRef = useRef(onAuthenticated);
    const [message, setMessage] = useState("INITIALIZING SECURITY...");
    const [isUnlocking, setIsUnlocking] = useState(false);
    const [previewReady, setPreviewReady] = useState(false);
    const [metrics, setMetrics] = useState({ mad: 0.0, cosine: 0.0 });
    
    // Hardware Selection State
    const [cameras, setCameras] = useState([]);
    const [selectedDeviceId, setSelectedDeviceId] = useState('');
    const [showOptions, setShowOptions] = useState(false);

    const choosePreferredCamera = (videoInputs) => {
        if (!videoInputs.length) return null;
        const savedDeviceId = localStorage.getItem('selectedWebcamId');
        if (savedDeviceId) {
            const saved = videoInputs.find((device) => device.deviceId === savedDeviceId);
            if (saved) return saved;
        }
        return videoInputs[0];
    };

    useEffect(() => {
        onAuthenticatedRef.current = onAuthenticated;
    }, [onAuthenticated]);

    useEffect(() => {
        const getCameras = async () => {
            try {
                const devices = await navigator.mediaDevices.enumerateDevices();
                const videoInputs = devices.filter(d => d.kind === 'videoinput');
                setCameras(videoInputs);
                const primary = choosePreferredCamera(videoInputs);
                if (primary) setSelectedDeviceId(primary.deviceId);
            } catch (err) { console.error("Failed to list cameras:", err); }
        };
        getCameras();
    }, []);

    useEffect(() => {
        if (!selectedDeviceId && cameras.length > 0) {
            setSelectedDeviceId(cameras[0].deviceId);
        }
    }, [selectedDeviceId, cameras]);

    useEffect(() => {
        if (!socket || !selectedDeviceId || isUnlocking) return;

        let cancelled = false;
        let stream = null;
        let interval = null;

        const startCapture = async () => {
            setPreviewReady(false);
            const previewEl = videoPreviewRef.current;
            const canvasEl = captureCanvasRef.current;

            const attachStream = (nextStream) => {
                if (cancelled) {
                    nextStream.getTracks().forEach(t => t.stop());
                    return;
                }

                stream = nextStream;
                if (!previewEl || !canvasEl) return;

                previewEl.srcObject = stream;
                previewEl.onloadedmetadata = () => {
                    canvasEl.width = previewEl.videoWidth;
                    canvasEl.height = previewEl.videoHeight;
                    setPreviewReady(true);
                    setMessage("IDENTITY SCANNER: ACTIVE");

                    if (interval) clearInterval(interval);
                    interval = setInterval(() => {
                        if (cancelled || previewEl.readyState < 2) return;
                        const ctx = canvasEl.getContext('2d');
                        ctx.drawImage(previewEl, 0, 0, canvasEl.width, canvasEl.height);
                        const b64 = canvasEl.toDataURL('image/jpeg', 0.5).split(',')[1];
                        socket.emit('auth_frame_upload', { image: b64 });
                    }, 250);
                };
            };

            try {
                const nextStream = await navigator.mediaDevices.getUserMedia({ 
                    video: { deviceId: { exact: selectedDeviceId }, width: 640, height: 480 }
                });
                attachStream(nextStream);
            } catch (err) { setMessage("HARDWARE_CONFLICT: CAMERA_LOCKED"); }

            // Fallback to default camera if the preferred device ID is stale/unavailable.
            if (!stream) {
                try {
                    const fallbackStream = await navigator.mediaDevices.getUserMedia({
                        video: { width: 640, height: 480 }
                    });
                    attachStream(fallbackStream);
                    setMessage("IDENTITY SCANNER: DEFAULT CAMERA");
                } catch (fallbackErr) {
                    setMessage("HARDWARE_CONFLICT: CAMERA_LOCKED");
                    console.error("Auth camera fallback failed:", fallbackErr);
                }
            }
        };

        startCapture();

        const handleAuthStatus = (data) => {
            if (data.authenticated && !isUnlocking) {
                setIsUnlocking(true);
                setMessage("IDENTITY CONFIRMED. ACCESS GRANTED.");
                setTimeout(() => onAuthenticatedRef.current?.(true), 2400);
            }
        };

        const handleMetrics = (data) => setMetrics(data);

        socket.on('auth_status', handleAuthStatus);
        socket.on('auth_metrics', handleMetrics);

        return () => {
            cancelled = true;
            if (stream) stream.getTracks().forEach(t => t.stop());
            if (interval) clearInterval(interval);
            socket.off('auth_status', handleAuthStatus);
            socket.off('auth_metrics', handleMetrics);
        };
    }, [socket, selectedDeviceId, isUnlocking]);

    return (
        <div className={`fixed inset-0 z-[9999] bg-black flex flex-col items-center justify-center font-mono overflow-hidden transition-all duration-1000 ${isUnlocking ? 'opacity-0 scale-105 pointer-events-none' : 'opacity-100'}`}>
            
            {/* AMBIENT HUD BACKGROUND */}
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(6,182,212,0.15)_0%,transparent_70%)]" />
            <div className="absolute inset-0 bg-[linear-gradient(rgba(18,16,16,0)_50%,rgba(0,0,0,0.25)_50%),linear-gradient(90deg,rgba(255,0,0,0.06),rgba(0,255,0,0.02),rgba(0,0,255,0.06))] z-10 bg-[length:100%_2px,3px_100%] pointer-events-none" />

            <div className="relative flex flex-col items-center gap-12 z-20">
                {/* HUD SCANNER CORE */}
                <div className="relative w-80 h-80 flex items-center justify-center">
                    
                    {/* Rotating Rings */}
                    <motion.div 
                        animate={{ rotate: 360 }}
                        transition={{ duration: 10, repeat: Infinity, ease: "linear" }}
                        className="absolute inset-0 border-2 border-dashed border-cyan-500/20 rounded-full"
                    />
                    <motion.div 
                        animate={{ rotate: -360 }}
                        transition={{ duration: 15, repeat: Infinity, ease: "linear" }}
                        className="absolute inset-4 border border-cyan-400/30 rounded-full"
                    />
                    <motion.div 
                        animate={{ rotate: 360 }}
                        transition={{ duration: 5, repeat: Infinity, ease: "linear" }}
                        className={`absolute inset-8 border-t-2 border-l-2 ${isUnlocking ? 'border-green-400' : 'border-cyan-400'} rounded-full opacity-60`}
                    />

                    {/* Circular Video Preview */}
                    <div className={`relative w-64 h-64 rounded-full overflow-hidden border-4 ${isUnlocking ? 'border-green-500 shadow-[0_0_40px_rgba(34,197,94,0.4)]' : 'border-cyan-500 shadow-[0_0_30px_rgba(6,182,212,0.2)]'} bg-black transition-all duration-700`}>
                        <video
                            ref={videoPreviewRef}
                            autoPlay
                            muted
                            playsInline
                            className={`w-full h-full object-cover transition-opacity duration-500 ${isUnlocking ? 'opacity-40 grayscale' : 'opacity-100'}`}
                            style={{ transform: isCameraFlipped ? 'scaleX(-1)' : 'none' }}
                        />
                        <canvas ref={captureCanvasRef} className="hidden" />
                        
                        {/* Scanning Line */}
                        <motion.div 
                            animate={{ top: ['0%', '100%', '0%'] }}
                            transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
                            className="absolute left-0 w-full h-0.5 bg-cyan-400 shadow-[0_0_15px_cyan] z-30"
                        />

                        {/* Overlay Icons */}
                        <AnimatePresence>
                            {isUnlocking && (
                                <motion.div 
                                    initial={{ scale: 0, opacity: 0 }}
                                    animate={{ scale: 1, opacity: 1 }}
                                    className="absolute inset-0 flex items-center justify-center bg-green-500/20 z-40"
                                >
                                    <ShieldCheck size={80} className="text-green-400 drop-shadow-[0_0_20px_rgba(74,222,128,0.8)]" />
                                </motion.div>
                            )}
                        </AnimatePresence>
                    </div>

                    {/* HUD Labels around the circle */}
                    <div className="absolute top-0 left-1/2 -translate-x-1/2 -translate-y-8 flex flex-col items-center">
                        <span className="text-[10px] text-cyan-500 font-bold tracking-[0.3em]">SECURE_LINK</span>
                        <div className="w-1 h-8 bg-gradient-to-b from-cyan-500 to-transparent" />
                    </div>
                </div>

                {/* STATUS BAR */}
                <div className="flex flex-col items-center gap-4 min-w-[400px]">
                    <div className={`text-2xl font-black tracking-[0.4em] ${isUnlocking ? 'text-green-400' : 'text-cyan-400'} drop-shadow-[0_0_10px_currentColor] transition-colors duration-700`}>
                        {message}
                    </div>
                    
                    {/* METRICS HUD */}
                    <div className="flex gap-12 mt-4 opacity-70">
                        <div className="flex flex-col items-center">
                            <span className="text-[8px] text-cyan-600 uppercase tracking-widest">Similarity_Score</span>
                            <span className="text-lg font-bold text-cyan-300">{(metrics.cosine * 100).toFixed(1)}%</span>
                        </div>
                        <div className="flex flex-col items-center">
                            <span className="text-[8px] text-cyan-600 uppercase tracking-widest">Deviation_MAR</span>
                            <span className="text-lg font-bold text-cyan-300">{metrics.mad.toFixed(4)}</span>
                        </div>
                        <div className="flex flex-col items-center">
                            <span className="text-[8px] text-cyan-600 uppercase tracking-widest">Core_Link</span>
                            <div className="flex gap-1 mt-1">
                                {[1, 2, 3, 4].map(i => (
                                    <motion.div 
                                        key={i}
                                        animate={{ opacity: [0.2, 1, 0.2] }}
                                        transition={{ duration: 1, repeat: Infinity, delay: i * 0.2 }}
                                        className="w-1 h-3 bg-cyan-500 rounded-full"
                                    />
                                ))}
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {/* CAMERA SELECT PANEL */}
            <div className="fixed bottom-12 left-1/2 -translate-x-1/2 flex flex-col items-center gap-2">
                {(() => {
                    const activeCamera = cameras.find(c => c.deviceId === selectedDeviceId);
                    const cameraLabel = activeCamera?.label ? activeCamera.label.substring(0, 20) : "SEARCHING...";
                    return (
                <button 
                    onClick={() => setShowOptions(!showOptions)}
                    className="group flex items-center gap-2 text-[10px] text-cyan-500/40 hover:text-cyan-400 transition-colors uppercase tracking-[0.2em]"
                >
                    <Activity size={12} className="group-hover:animate-pulse" />
                    SELECT_UPLINK: {cameraLabel}
                </button>
                    );
                })()}
                
                <AnimatePresence>
                    {showOptions && (
                        <motion.div 
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, y: 10 }}
                            className="bg-black/80 backdrop-blur-md border border-cyan-500/20 rounded-md p-2 flex flex-col gap-1 min-w-[200px]"
                        >
                            {cameras.map(cam => (
                                <button
                                    key={cam.deviceId}
                                    onClick={() => { setSelectedDeviceId(cam.deviceId); setShowOptions(false); }}
                                    className={`text-left px-3 py-2 rounded text-[10px] uppercase transition-colors ${selectedDeviceId === cam.deviceId ? 'bg-cyan-500/20 text-cyan-400' : 'text-cyan-500/40 hover:bg-cyan-500/10'}`}
                                >
                                    {cam.label || `LENS_${cam.deviceId.substring(0, 4)}`}
                                </button>
                            ))}
                        </motion.div>
                    )}
                </AnimatePresence>
            </div>
        </div>
    );
};

export default AuthLock;
