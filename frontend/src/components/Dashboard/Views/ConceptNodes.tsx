import { useState, useEffect } from 'react';
import { FileText, Tag, Network } from 'lucide-react';
import { fetchObsidianGraph } from '../../../lib/api';

const COLORS = ['bg-purple-500', 'bg-cyan-500', 'bg-blue-500', 'bg-emerald-500', 'bg-rose-500'];

export function ConceptNodes() {
  const [nodes, setNodes] = useState<any[]>([]);
  const [totalCount, setTotalCount] = useState(0);

  useEffect(() => {
    let mounted = true;
    fetchObsidianGraph().then(data => {
      if (!mounted) return;
      const parsedNodes = data.nodes || [];
      setTotalCount(parsedNodes.length);
      
      // Take up to 12 nodes for the grid
      const displayNodes = parsedNodes.slice(0, 12).map((n: any, i: number) => ({
        title: n.label,
        tags: ['Obsidian', 'Note'],
        date: 'Recent',
        color: COLORS[i % COLORS.length]
      }));
      setNodes(displayNodes);
    });
    return () => { mounted = false; };
  }, []);

  return (
    <div className="w-full h-full flex flex-col p-8 overflow-y-auto">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h2 className="text-2xl font-light text-white mb-2">Concept Nodes</h2>
          <p className="text-white/50 text-sm">{totalCount} thoughts synced from Obsidian Vault.</p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-white/80 transition-colors">
          <Network size={16} />
          <span className="text-sm font-medium">Graph View</span>
        </button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
        {nodes.map((node, i) => (
          <div key={i} className="group p-5 rounded-2xl bg-white/5 border border-white/10 hover:bg-white/10 hover:border-purple-500/30 transition-all cursor-pointer flex flex-col h-40 relative overflow-hidden">
            <div className={`absolute top-0 left-0 w-1 h-full ${node.color} opacity-50 group-hover:opacity-100 transition-opacity`}></div>
            
            <div className="flex items-start justify-between mb-auto">
              <div className="flex items-center gap-2 text-white/40 group-hover:text-white/70 transition-colors">
                <FileText size={16} />
              </div>
              <span className="text-[10px] text-white/30 uppercase tracking-widest">{node.date}</span>
            </div>
            
            <h3 className="text-white/90 font-medium leading-snug mb-4 group-hover:text-purple-300 transition-colors">
              {node.title}
            </h3>
            
            <div className="flex flex-wrap gap-2">
              {node.tags.map((tag: string) => (
                <span key={tag} className="flex items-center gap-1 text-[10px] px-2 py-1 rounded-md bg-black/40 text-white/60">
                  <Tag size={10} />
                  {tag}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
