import React, { useEffect, useRef } from 'react';
import { motion } from 'framer-motion';

const Visualizer = ({ audioDataRef, isListening, intensity = 0, width = 600, height = 400 }) => {
    const canvasRef = useRef(null);

    // Sync non-ref props to internal refs for the animation loop
    const intensityRef = useRef(intensity);
    const isListeningRef = useRef(isListening);

    useEffect(() => {
        intensityRef.current = intensity;
        isListeningRef.current = isListening;
    }, [intensity, isListening]);

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;

        // Ensure canvas internal resolution matches display size for sharpness
        canvas.width = width;
        canvas.height = height;

        const ctx = canvas.getContext('2d');
        let animationId;

        const draw = () => {
            const w = canvas.width;
            const h = canvas.height;
            const centerX = w / 2;
            const centerY = h / 2;

            // Calculate real-time intensity from raw binary buffer
            let dynamicIntensity = 0;
            if (audioDataRef.current && audioDataRef.current.length > 0) {
                const data = audioDataRef.current;
                // Use the view for 16-bit signed PCM (Gemini Standard)
                // We ensure alignment by checking length
                const sampleCount = Math.floor(data.length / 2);
                if (sampleCount > 0) {
                    const samples = new Int16Array(data.buffer, data.byteOffset, sampleCount);
                    let sum = 0;
                    for (let i = 0; i < samples.length; i++) {
                        const val = samples[i] / 32768;
                        sum += val * val;
                    }
                    const rms = Math.sqrt(sum / samples.length);
                    dynamicIntensity = rms * 3.5; // Slightly higher scale for 16-bit
                }
            }

            // Blend with prop-based intensity or use as fallback
            const currentIntensity = Math.max(dynamicIntensity, intensityRef.current);
            const currentIsListening = isListeningRef.current;

            const baseRadius = Math.min(w, h) * 0.25;
            const radius = baseRadius + (currentIntensity * 60);

            ctx.clearRect(0, 0, w, h);

            // Base Circle (Glow)
            ctx.beginPath();
            ctx.arc(centerX, centerY, radius - 10, 0, Math.PI * 2);
            ctx.strokeStyle = 'rgba(6, 182, 212, 0.1)';
            ctx.lineWidth = 2;
            ctx.stroke();

            if (!currentIsListening) {
                // Idle State: Breathing Circle
                const time = Date.now() / 1000;
                const breath = Math.sin(time * 2) * 5;

                ctx.beginPath();
                ctx.arc(centerX, centerY, radius + breath, 0, Math.PI * 2);
                ctx.strokeStyle = 'rgba(34, 211, 238, 0.5)';
                ctx.lineWidth = 4;
                ctx.shadowBlur = 20;
                ctx.shadowColor = '#22d3ee';
                ctx.stroke();
                ctx.shadowBlur = 0;
            } else {
                // Active State: Just the Circle causing the pulse
                ctx.beginPath();
                ctx.arc(centerX, centerY, radius, 0, Math.PI * 2);
                ctx.strokeStyle = 'rgba(34, 211, 238, 0.8)';
                ctx.lineWidth = 4;
                ctx.shadowBlur = 20;
                ctx.shadowColor = '#22d3ee';
                ctx.stroke();
                ctx.shadowBlur = 0;
            }

            animationId = requestAnimationFrame(draw);
        };

        draw();
        return () => cancelAnimationFrame(animationId);
    }, [width, height]);

    return (
        <div className="relative" style={{ width, height }}>
            {/* Central Logo/Text */}
            <div className="absolute inset-0 flex items-center justify-center z-10 pointer-events-none">
                <motion.div
                    animate={{ scale: isListening ? [1, 1.1, 1] : 1 }}
                    transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
                    className="text-cyan-100 font-bold tracking-widest drop-shadow-[0_0_15px_rgba(34,211,238,0.8)]"
                    style={{ fontSize: Math.min(width, height) * 0.1 }}
                >
                    ORION
                </motion.div>
            </div>

            <canvas
                ref={canvasRef}
                style={{ width: '100%', height: '100%' }}
            />
        </div>
    );
};

export default Visualizer;
