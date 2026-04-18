import React, { useEffect, useRef } from 'react';

const ChatModule = ({
    messages,
    inputValue,
    setInputValue,
    handleSend,
    isModularMode = false,
    activeDragElement,
    position, // Optional now
    width = '100%',
    height = '100%',
    onMouseDown
}) => {
    const messagesEndRef = useRef(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    // Handle fallback for position
    const containerStyle = position ? {
        left: position.x || 0,
        top: position.y || 0,
        transform: 'translate(-50%, 0)', // Aligned top-center for modular mode
        width: width,
        height: height,
        position: 'absolute'
    } : {
        width: '100%',
        height: '100%',
        position: 'relative'
    };

    return (
        <div
            id="chat"
            onMouseDown={onMouseDown}
            className={`px-6 py-4 pointer-events-auto transition-all duration-200 
            backdrop-blur-xl bg-black/40 border border-white/10 shadow-2xl rounded-2xl
            ${isModularMode ? (activeDragElement === 'chat' ? 'ring-2 ring-green-500' : 'ring-1 ring-yellow-500/30') : ''}
            flex flex-col relative overflow-hidden
        `}
            style={containerStyle}
        >
            {/* HUD Grain Overlay */}
            <div className="absolute inset-0 opacity-10 pointer-events-none mix-blend-overlay bg-[radial-gradient(circle_at_20%_20%,rgba(34,211,238,0.08)_0,transparent_22%),radial-gradient(circle_at_80%_30%,rgba(255,255,255,0.04)_0,transparent_18%),radial-gradient(circle_at_40%_80%,rgba(34,211,238,0.05)_0,transparent_20%)]"></div>
            
            <div className="flex flex-col gap-3 overflow-y-auto mb-4 scrollbar-hide mask-image-gradient relative z-10 flex-1">
                {messages && messages.slice(-20).map((msg, i) => (
                    <div key={i} className="text-sm border-l-2 border-cyan-800/50 pl-3 py-1 group hover:border-cyan-400 transition-colors">
                        <div className="flex items-center gap-2 mb-0.5">
                            <span className="text-cyan-600 font-mono text-[8px] opacity-70 tracking-tighter uppercase">[{msg.time}]</span> 
                            <span className="font-bold text-cyan-400/80 text-[10px] uppercase tracking-widest">{msg.sender}</span>
                        </div>
                        <div className="text-gray-300 leading-relaxed font-sans text-xs">{msg.text}</div>
                    </div>
                ))}
                <div ref={messagesEndRef} />
            </div>

            <div className="flex gap-2 relative z-10 mt-auto pt-2">
                <div className="relative flex-1 group">
                     <div className="absolute -inset-0.5 bg-gradient-to-r from-cyan-500 to-blue-500 rounded-lg blur opacity-10 group-focus-within:opacity-20 transition duration-500"></div>
                     <input
                        type="text"
                        value={inputValue}
                        onChange={(e) => setInputValue(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                        placeholder="INPUT_COMMAND >_"
                        className="relative w-full bg-black/60 border border-cyan-700/30 rounded-lg p-3 text-cyan-50 text-xs font-mono focus:outline-none focus:border-cyan-400 transition-all placeholder-cyan-900/50"
                    />
                </div>
            </div>

            {isModularMode && <div className={`absolute -top-6 left-0 text-xs font-bold tracking-widest ${activeDragElement === 'chat' ? 'text-green-500' : 'text-yellow-500/50'}`}>CHAT MODULE</div>}
        </div>
    );
};

export default ChatModule;
