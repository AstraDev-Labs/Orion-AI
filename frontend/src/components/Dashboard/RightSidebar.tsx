import { ChevronLeft, ChevronRight, Maximize2 } from 'lucide-react';

export function RightSidebar() {
  const days = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'];
  const dates = [
    [27, 28, 29, 30, 1, 2, 3],
    [4, 5, 6, 7, 8, 9, 10],
    [11, 12, 13, 14, 15, 16, 17],
    [18, 19, 20, 21, 22, 23, 24],
    [25, 26, 27, 28, 29, 30, 31],
  ];

  return (
    <div className="w-[280px] flex-shrink-0 h-full flex flex-col p-6 border-l border-white/5 border-dashed">
      
      {/* Calendar Header */}
      <div className="flex items-center justify-between mb-8">
        <h3 className="text-white/90 font-medium tracking-wide">October 2023</h3>
        <div className="flex items-center gap-3 text-white/40">
          <ChevronLeft size={16} className="cursor-pointer hover:text-white/80 transition-colors" />
          <Maximize2 size={14} className="cursor-pointer hover:text-white/80 transition-colors" />
          <ChevronRight size={16} className="cursor-pointer hover:text-white/80 transition-colors" />
        </div>
      </div>

      {/* Calendar Grid */}
      <div className="w-full">
        {/* Days Header */}
        <div className="grid grid-cols-7 mb-4">
          {days.map(day => (
            <div key={day} className="text-center text-[11px] font-medium text-white/40 uppercase tracking-wider">
              {day}
            </div>
          ))}
        </div>

        {/* Dates */}
        <div className="flex flex-col gap-2">
          {dates.map((row, i) => (
            <div key={i} className="grid grid-cols-7 gap-1">
              {row.map((date, j) => {
                const isCurrentMonth = !(i === 0 && date > 20);
                const isSelected = date === 16 && isCurrentMonth;
                const hasEvent = (date === 2 || date === 9) && isCurrentMonth;

                return (
                  <div 
                    key={`${i}-${j}`} 
                    className={`
                      aspect-square flex items-center justify-center text-xs rounded-md cursor-pointer transition-all
                      ${!isCurrentMonth ? 'text-white/20' : 'text-white/70 hover:bg-white/5'}
                      ${isSelected ? 'bg-purple-500 text-white shadow-[0_0_15px_rgba(168,85,247,0.5)] glow-text-purple' : ''}
                      ${hasEvent && !isSelected ? 'text-purple-300 font-bold' : ''}
                    `}
                  >
                    {date}
                    {hasEvent && <div className="absolute w-1 h-1 bg-purple-400 rounded-full bottom-1 opacity-50"></div>}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
      
    </div>
  );
}
