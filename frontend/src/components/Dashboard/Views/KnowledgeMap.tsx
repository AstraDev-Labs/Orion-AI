import { useState, useEffect } from 'react';
import { Compass } from 'lucide-react';
import { fetchObsidianGraph } from '../../../lib/api';

export function KnowledgeMap() {
  const [nodes, setNodes] = useState<any[]>([]);
  const [edges, setEdges] = useState<any[]>([]);

  useEffect(() => {
    let mounted = true;
    fetchObsidianGraph().then(data => {
      if (!mounted) return;
      
      const parsedNodes = data.nodes || [];
      const parsedEdges = data.edges || [];
      
      const cx = 500;
      const cy = 300;
      const radius = 220;
      
      const positionedNodes = parsedNodes.map((node: any, i: number) => {
        // Distribute nodes roughly in a circle/spiral
        const angle = (i / parsedNodes.length) * Math.PI * 2;
        // add some random variation to the radius
        const r = radius * (0.4 + 0.6 * Math.random());
        return {
          ...node,
          x: cx + Math.cos(angle) * r,
          y: cy + Math.sin(angle) * r
        };
      });
      
      setNodes(positionedNodes);
      setEdges(parsedEdges);
    });
    
    return () => { mounted = false; };
  }, []);

  const getNode = (id: string) => nodes.find(n => String(n.id) === String(id));

  return (
    <div className="w-full h-full flex flex-col p-8 relative overflow-hidden">
      <div className="absolute top-8 left-8 z-10 pointer-events-none">
        <h2 className="text-2xl font-light text-white mb-2">Knowledge Map</h2>
        <p className="text-white/50 text-sm">Visualizing {nodes.length} connected concepts.</p>
      </div>

      <div className="absolute inset-0 flex items-center justify-center pointer-events-auto">
        <svg className="w-full h-full opacity-40" viewBox="0 0 1000 600">
          <defs>
            <radialGradient id="nodeGlow" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="#a855f7" stopOpacity="0.8" />
              <stop offset="100%" stopColor="#a855f7" stopOpacity="0" />
            </radialGradient>
          </defs>
          
          {/* Edges */}
          {edges.map((edge, i) => {
            const source = getNode(edge.source);
            const target = getNode(edge.target);
            if (!source || !target) return null;
            return (
              <line key={i} x1={source.x} y1={source.y} x2={target.x} y2={target.y} stroke="rgba(255,255,255,0.15)" strokeWidth="1" />
            );
          })}
          
          {/* Nodes */}
          {nodes.map(node => (
            <g key={node.id}>
              <circle cx={node.x} cy={node.y} r="20" fill="url(#nodeGlow)" />
              <circle cx={node.x} cy={node.y} r="3" fill="#fff" />
              <text x={node.x} y={node.y - 12} fill="rgba(255,255,255,0.7)" fontSize="10" textAnchor="middle" letterSpacing="0.5">
                {node.label.length > 20 ? node.label.substring(0, 20) + '...' : node.label}
              </text>
            </g>
          ))}
          
          {nodes.length === 0 && (
             <text x="500" y="300" fill="rgba(255,255,255,0.5)" fontSize="14" textAnchor="middle">No nodes found in Obsidian Vault</text>
          )}
        </svg>
      </div>

      <div className="absolute bottom-8 right-8 z-10 flex gap-2">
        <button className="p-3 bg-white/5 hover:bg-white/10 rounded-full border border-white/10 text-white/50 transition-colors">
          <Compass size={20} />
        </button>
      </div>
    </div>
  );
}
