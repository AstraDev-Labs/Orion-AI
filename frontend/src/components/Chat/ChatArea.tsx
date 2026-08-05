import { useRef, useEffect } from 'react';
import { MessageBubble } from './MessageBubble';
import { InputArea } from './InputArea';
import { StreamingDots } from './StreamingDots';
import { useAppStore } from '../../lib/store';
import { Activity } from 'lucide-react';

function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

export function ChatArea() {
  const messages = useAppStore((s) => s.messages);
  const streamState = useAppStore((s) => s.streamState);
  const listRef = useRef<HTMLDivElement>(null);
  const shouldAutoScroll = useRef(true);

  useEffect(() => {
    if (shouldAutoScroll.current && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, streamState.content]);

  const handleScroll = () => {
    if (!listRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = listRef.current;
    shouldAutoScroll.current = scrollHeight - scrollTop - clientHeight < 100;
  };

  const isEmpty = messages.length === 0 && !streamState.isStreaming;

  return (
    <div className="flex flex-col h-full relative z-10 w-full max-w-4xl mx-auto">
      <div
        ref={listRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-4 relative scroll-smooth"
      >
        {isEmpty ? (
          <div className="flex flex-col items-center justify-center h-full px-4 relative opacity-40">
            <p className="text-sm text-center max-w-md font-light text-white/50 tracking-wider">
              Waiting for input...
            </p>
          </div>
        ) : (
          <div className="py-6">
            {messages.map((msg, i) => {
              const isLastAssistant = i === messages.length - 1 && msg.role === 'assistant';
              return (
                <MessageBubble
                  key={msg.id}
                  message={msg}
                  isLive={isLastAssistant && streamState.isStreaming}
                />
              );
            })}
            {streamState.isStreaming && streamState.content === '' && (
              <div className="flex justify-start mb-6 px-4">
                 <div className="px-4 py-3 border border-white/5 bg-white/5 backdrop-blur-md rounded-2xl flex items-center gap-3">
                   <Activity size={16} className="text-purple-400 animate-pulse" />
                   <span className="font-light text-sm text-white/70">Orion is thinking</span>
                   <StreamingDots phase={streamState.phase} />
                 </div>
              </div>
            )}
          </div>
        )}
      </div>
      <div className="px-4 pb-6">
         <InputArea />
      </div>
    </div>
  );
}
