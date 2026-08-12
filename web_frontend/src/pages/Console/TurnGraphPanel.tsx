import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Maximize, ZoomIn, ZoomOut } from "lucide-react";

interface TurnSummary {
  id: string;
  turn_no: number;
  parent_id: string | null;
  parent_turn_no: number | null;
  sender: string;
  branch_name: string;
  branch_id: string;
}

interface TreeNode extends TurnSummary {
  children: TreeNode[];
}

interface TurnGraphPanelProps {
  turns: TurnSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  error: string | null;
  currentId: string | null;
}

/* ── 布局尺寸 ── */
const NODE_W = 150; // 节点宽
const NODE_H = 44; // 节点高
const ROW_H = 64; // 纵向行高（深度方向）
const SLOT_W = NODE_W + 28; // 横向叶子槽位宽
const ROOT_GAP = 56; // 多根（重新开局）之间的纵向间距
/** 默认显示比例：聚焦当前节点附近时的缩放（可读比例，非整树适配） */
const INITIAL_SCALE = 0.8;

interface Pos {
  node: TreeNode;
  x: number; // 节点左上角 x（世界坐标）
  y: number; // 节点左上角 y（世界坐标）
  isBranchStart: boolean;
}

interface Edge {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

interface View {
  x: number;
  y: number;
  scale: number;
}

/** 由平铺 turn 数组按 parent_id 重建会话森林（main 链 + 每次重新开局的新链 + 各分支子树） */
function buildForest(turns: TurnSummary[]): TreeNode[] {
  const map = new Map<string, TreeNode>();
  for (const t of turns) map.set(t.id, { ...t, children: [] });

  const roots: TreeNode[] = [];
  for (const node of map.values()) {
    const parent = node.parent_id ? map.get(node.parent_id) : undefined;
    if (parent) parent.children.push(node);
    else roots.push(node);
  }

  const sortRec = (ns: TreeNode[]) => {
    ns.sort((a, b) => a.turn_no - b.turn_no);
    ns.forEach((n) => sortRec(n.children));
  };
  sortRec(roots);
  return roots;
}

/** 子树叶子数（单链=1，分叉=分支叶子之和） */
function countLeaves(n: TreeNode): number {
  return n.children.length === 0 ? 1 : n.children.reduce((s, c) => s + countLeaves(c), 0);
}

/** 子树最大深度（相对该节点） */
function maxDepth(n: TreeNode): number {
  return n.children.length === 0 ? 0 : 1 + Math.max(...n.children.map(maxDepth));
}

/** 子树节点总数 */
function subtreeSize(n: TreeNode): number {
  return 1 + n.children.reduce((s, c) => s + subtreeSize(c), 0);
}

/**
 * 族谱式分层布局：y=深度×行高，x=叶子槽位分配。
 * 单链节点与其唯一子节点同 x（主链笔直向下）；多子节点在父下方从左到右排开。
 * 多个根（重新开局）纵向依次堆叠。
 */
function layout(roots: TreeNode[]): { positions: Map<string, Pos>; edges: Edge[]; width: number; height: number } {
  const positions = new Map<string, Pos>();
  const edges: Edge[] = [];
  let width = 0;
  let blockTop = 0;

  const place = (
    node: TreeNode,
    parent: TreeNode | null,
    depth: number,
    yBase: number,
    slotLeft: number,
    slotRight: number
  ) => {
    const cx = ((slotLeft + slotRight) / 2) * SLOT_W;
    const y = yBase + depth * ROW_H;
    const isBranchStart = parent === null || node.branch_id !== parent.branch_id;
    positions.set(node.id, { node, x: cx - NODE_W / 2, y, isBranchStart });
    if (parent) {
      const p = positions.get(parent.id)!;
      edges.push({ x1: p.x + NODE_W / 2, y1: p.y + NODE_H, x2: cx, y2: y });
    }
    let cursor = slotLeft;
    node.children.forEach((c) => {
      const span = countLeaves(c);
      place(c, node, depth + 1, yBase, cursor, cursor + span);
      cursor += span;
    });
  };

  for (const root of roots) {
    place(root, null, 0, blockTop, 0, countLeaves(root));
    width = Math.max(width, countLeaves(root) * SLOT_W);
    blockTop += (maxDepth(root) + 1) * ROW_H + ROOT_GAP;
  }

  return { positions, edges, width, height: Math.max(0, blockTop - ROOT_GAP) };
}

export default function TurnGraphPanel({ turns, selectedId, onSelect, error, currentId }: TurnGraphPanelProps) {
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());
  const [view, setView] = useState<View>({ x: 0, y: 0, scale: 1 });
  const containerRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ sx: number; sy: number; ox: number; oy: number; moved: boolean } | null>(null);
  const focusedRef = useRef(false);
  const followArmedRef = useRef(false);
  const userAdjustedRef = useRef(false);
  const positionsRef = useRef<Map<string, Pos>>(new Map());

  const forest = useMemo(() => buildForest(turns), [turns]);
  const origMap = useMemo(() => {
    const m = new Map<string, TreeNode>();
    const walk = (ns: TreeNode[]) => ns.forEach((n) => { m.set(n.id, n); walk(n.children); });
    walk(forest);
    return m;
  }, [forest]);

  // 折叠状态裁剪出可见树（折叠节点的子树整体隐藏）
  const visible = useMemo(() => {
    const prune = (n: TreeNode): TreeNode => ({
      ...n,
      children: collapsed.has(n.id) ? [] : n.children.map(prune),
    });
    return forest.map(prune);
  }, [forest, collapsed]);

  const { positions, edges, width, height } = useMemo(() => layout(visible), [visible]);
  positionsRef.current = positions;

  const toggle = (id: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const fit = useCallback(() => {
    const el = containerRef.current;
    if (!el || visible.length === 0) return;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    const pad = 24;
    const scale = Math.min(
      (rect.width - pad * 2) / Math.max(1, width),
      (rect.height - pad * 2) / Math.max(1, height),
      1.25
    );
    setView({
      scale: Math.max(0.08, Math.min(3, scale)),
      x: (rect.width - width * scale) / 2,
      y: (rect.height - height * scale) / 2,
    });
  }, [visible.length, width, height]);

  // 首次加载：聚焦当前节点附近（可读比例）；无当前节点则适配整树
  useEffect(() => {
    if (focusedRef.current || visible.length === 0) return;
    const pos = currentId ? positionsRef.current.get(currentId) : undefined;
    const el = containerRef.current;
    if (!pos || !el) {
      // 当前节点尚未就绪：若确无 head（如刚重新开局），先展示整树
      if (currentId === null) fit();
      return;
    }
    focusedRef.current = true;
    followArmedRef.current = true;
    const rect = el.getBoundingClientRect();
    setView({
      scale: INITIAL_SCALE,
      x: rect.width / 2 - (pos.x + NODE_W / 2) * INITIAL_SCALE,
      y: rect.height / 2 - (pos.y + NODE_H / 2) * INITIAL_SCALE,
    });
  }, [visible.length, currentId, fit]);

  // 容器尺寸变化（未手动调整视图、且已聚焦完成后）重新适配
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    let prev: { w: number; h: number } | null = null;
    const ro = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const { width, height } = entry.contentRect;
      // 首次回调（observe 立即触发一次）跳过，避免覆盖聚焦视图
      if (!prev || (prev.w === width && prev.h === height)) {
        prev = { w: width, h: height };
        return;
      }
      prev = { w: width, h: height };
      if (focusedRef.current && !userAdjustedRef.current) fit();
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [fit]);

  // 当前节点（新轮次到达/切换分支）移出视野时平移到可见，保持用户缩放比例
  useEffect(() => {
    if (!currentId || !followArmedRef.current) return;
    const pos = positionsRef.current.get(currentId);
    const el = containerRef.current;
    if (!pos || !el) return;
    const rect = el.getBoundingClientRect();
    const margin = 48;
    setView((v) => {
      const sx = (pos.x + NODE_W / 2) * v.scale + v.x;
      const sy = (pos.y + NODE_H / 2) * v.scale + v.y;
      const out = sx < margin || sx > rect.width - margin || sy < margin || sy > rect.height - margin;
      if (!out) return v;
      return {
        ...v,
        x: rect.width / 2 - (pos.x + NODE_W / 2) * v.scale,
        y: rect.height / 2 - (pos.y + NODE_H / 2) * v.scale,
      };
    });
  }, [currentId]);

  // 滚轮缩放（以光标为中心）；React 的 onWheel 是 passive 的，需原生非 passive 监听
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      userAdjustedRef.current = true;
      const rect = el.getBoundingClientRect();
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;
      const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
      setView((v) => {
        const ns = Math.max(0.08, Math.min(3, v.scale * factor));
        const k = ns / v.scale;
        return { scale: ns, x: cx - (cx - v.x) * k, y: cy - (cy - v.y) * k };
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const zoomBy = (factor: number) => {
    userAdjustedRef.current = true;
    const el = containerRef.current;
    setView((v) => {
      const ns = Math.max(0.08, Math.min(3, v.scale * factor));
      const k = ns / v.scale;
      const cx = (el?.clientWidth ?? 0) / 2;
      const cy = (el?.clientHeight ?? 0) / 2;
      return { scale: ns, x: cx - (cx - v.x) * k, y: cy - (cy - v.y) * k };
    });
  };

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    // 注意：此时不能 setPointerCapture —— 会把 pointerup 目标变成容器，
    // 导致节点/按钮的 click 事件被吞掉。仅拖拽真正开始时才捕获。
    dragRef.current = { sx: e.clientX, sy: e.clientY, ox: view.x, oy: view.y, moved: false };
  };

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const d = dragRef.current;
    if (!d) return;
    const dx = e.clientX - d.sx;
    const dy = e.clientY - d.sy;
    if (Math.abs(dx) + Math.abs(dy) > 4) {
      if (!d.moved) {
        d.moved = true;
        e.currentTarget.setPointerCapture(e.pointerId);
        userAdjustedRef.current = true;
      }
      setView((v) => ({ ...v, x: d.ox + dx, y: d.oy + dy }));
    }
  };

  const onPointerUp = () => {
    dragRef.current = null;
  };

  if (error) {
    return <div className="p-3 text-error text-xs">{error}</div>;
  }

  if (turns.length === 0) {
    return (
      <div className="p-10 text-muted-foreground text-center text-sm">
        暂无轮次
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="relative flex-1 min-h-0 overflow-hidden rounded-lg border border-border bg-surface"
      style={{
        // 点阵网格随视图平移缩放（Git graph 风格）
        backgroundImage: "radial-gradient(var(--color-border-val) 1px, transparent 1px)",
        backgroundSize: `${Math.max(10, 24 * view.scale)}px ${Math.max(10, 24 * view.scale)}px`,
        backgroundPosition: `${view.x}px ${view.y}px`,
        cursor: dragRef.current?.moved ? "grabbing" : "grab",
        touchAction: "none",
      }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerLeave={onPointerUp}
    >
      <svg className="absolute inset-0 w-full h-full overflow-hidden">
        <g transform={`translate(${view.x}, ${view.y}) scale(${view.scale})`}>
          {/* 连线：父底 → 子顶 的平滑贝塞尔（树杈感） */}
          {edges.map((e, i) => {
            const dy = Math.max(14, Math.min(30, (e.y2 - e.y1) / 2));
            return (
              <path
                key={i}
                d={`M ${e.x1} ${e.y1} C ${e.x1} ${e.y1 + dy}, ${e.x2} ${e.y2 - dy}, ${e.x2} ${e.y2}`}
                fill="none"
                stroke="var(--color-border-val)"
                strokeWidth={1.5}
              />
            );
          })}

          {/* 节点卡片 */}
          {[...positions.values()].map(({ node, x, y, isBranchStart }) => {
            const orig = origMap.get(node.id);
            const forkCount = orig?.children.length ?? 0;
            const isCollapsed = collapsed.has(node.id);
            return (
              <g key={node.id} transform={`translate(${x}, ${y})`}>
                <foreignObject x={0} y={0} width={NODE_W} height={NODE_H}>
                  <div
                    data-turn-id={node.id}
                    className={`relative h-full w-full flex flex-col justify-center gap-1 px-2.5 rounded-md border cursor-pointer transition-[filter] duration-150 hover:brightness-[.97] ${
                      selectedId === node.id
                        ? "bg-primary-container border-primary text-primary"
                        : "bg-surface-container-low border-border text-fg"
                    } ${currentId === node.id ? "ring-2 ring-primary/70" : ""}`}
                    onClick={() => onSelect(node.id)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => { if (e.key === "Enter") onSelect(node.id); }}
                  >
                    <div className="flex items-center gap-1.5">
                      <span className="text-sm font-semibold whitespace-nowrap leading-none">
                        #{String(node.turn_no).padStart(3, "0")}
                      </span>
                      <span className="text-xs text-muted-foreground truncate min-w-0 flex-1 leading-none">
                        {node.sender || "系统"}
                      </span>
                      {forkCount > 1 && (
                        <button
                          type="button"
                          title={isCollapsed ? `展开子树（${forkCount} 个子节点）` : "折叠子树"}
                          onClick={(e) => { e.stopPropagation(); toggle(node.id); }}
                          className={`flex items-center shrink-0 px-1.5 py-px rounded-full text-[10px] font-semibold leading-none cursor-pointer transition-colors ${
                            isCollapsed
                              ? "bg-primary text-white"
                              : "bg-surface-container-high text-muted-foreground hover:text-fg"
                          }`}
                        >
                          {isCollapsed ? "+" : "−"}{forkCount}
                        </button>
                      )}
                    </div>
                    <div className="flex items-center justify-between gap-1.5">
                      {isBranchStart && node.branch_name ? (
                        <span className="text-[10px] text-muted-foreground truncate" title={node.branch_name}>
                          {node.branch_name}
                        </span>
                      ) : (
                        <span />
                      )}
                      {currentId === node.id && (
                        <span className="text-[10px] font-bold px-1 py-px rounded-sm bg-primary text-white leading-none shrink-0">
                          当前
                        </span>
                      )}
                    </div>
                  </div>
                </foreignObject>
              </g>
            );
          })}
        </g>
      </svg>

      {/* 缩放/适配控制 */}
      <div className="absolute top-2 right-2 flex flex-col gap-1">
        <button
          type="button"
          onClick={() => zoomBy(1.25)}
          title="放大"
          className="w-7 h-7 flex items-center justify-center rounded-md bg-surface-container-high text-fg shadow-card cursor-pointer hover:brightness-[.97]"
        >
          <ZoomIn className="w-4 h-4" />
        </button>
        <button
          type="button"
          onClick={() => zoomBy(1 / 1.25)}
          title="缩小"
          className="w-7 h-7 flex items-center justify-center rounded-md bg-surface-container-high text-fg shadow-card cursor-pointer hover:brightness-[.97]"
        >
          <ZoomOut className="w-4 h-4" />
        </button>
        <button
          type="button"
          onClick={fit}
          title="适配画布"
          className="w-7 h-7 flex items-center justify-center rounded-md bg-surface-container-high text-fg shadow-card cursor-pointer hover:brightness-[.97]"
        >
          <Maximize className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
