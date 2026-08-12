import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronRight, Maximize, ZoomIn, ZoomOut } from "lucide-react";

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
const BRANCH_GAP = 56; // 主干列与旁支块、块与块之间的水平间距
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

/** 子树节点总数 */
function subtreeSize(n: TreeNode): number {
  return 1 + n.children.reduce((s, c) => s + subtreeSize(c), 0);
}

interface SubEntry {
  node: TreeNode;
  /** 相对子树根左侧的槽位中心 */
  center: number;
  /** 相对子树根的深度 */
  depth: number;
  parentBranchId: string | null;
}

interface SubLayout {
  /** 子树叶子数（占用的槽位数） */
  width: number;
  entries: SubEntry[];
}

/** 族谱式子树布局（相对坐标）：单链笔直向下，分叉按叶子槽位横向展开 */
function layoutSubtree(node: TreeNode, depth: number, parentBranchId: string | null): SubLayout {
  if (node.children.length === 0) {
    return { width: 1, entries: [{ node, center: 0.5, depth, parentBranchId }] };
  }
  const childLayouts = node.children.map((c) => layoutSubtree(c, depth + 1, node.branch_id));
  const width = childLayouts.reduce((s, l) => s + l.width, 0);
  let cursor = 0;
  const entries: SubEntry[] = [];
  for (const cl of childLayouts) {
    for (const e of cl.entries) entries.push({ ...e, center: cursor + e.center });
    cursor += cl.width;
  }
  entries.push({ node, center: width / 2, depth, parentBranchId });
  return { width, entries };
}

/** 旁支组：同一父节点的多个旁支子树合并为一组（组内叶子槽位展开） */
interface Group {
  depthBase: number;
  /** 组内最大深度（决定占用的行区间） */
  maxDepth: number;
  /** 组宽度（叶子数） */
  width: number;
  entries: SubEntry[];
}

function makeGroup(children: TreeNode[], depthBase: number, parentBranchId: string | null): Group {
  const childLayouts = children.map((c) => layoutSubtree(c, 0, parentBranchId));
  const width = childLayouts.reduce((s, l) => s + l.width, 0);
  let cursor = 0;
  const entries: SubEntry[] = [];
  for (const cl of childLayouts) {
    for (const e of cl.entries) entries.push({ ...e, center: cursor + e.center });
    cursor += cl.width;
  }
  const maxDepth = entries.reduce((m, e) => Math.max(m, e.depth), 0);
  return { depthBase, maxDepth, width, entries };
}

/**
 * Open WebUI 风格布局：
 * - 主干列 = 当前节点(head) → 根 的祖先链，竖直排在最左边
 * - head 被折叠不可见时，取其最近可见祖先作为主干终点（折叠后"所属的节点"），
 *   主干列仍从根竖直排在最左，不因 head 消失而退化为旁支组模式
 * - 其余分支作为"旁支组"装箱到主干右侧的轨道中：行区间不冲突的分支共享同一列，
 *   只有真正重叠的才另开新列，避免图被拉得太宽
 */
function layout(
  visibleForest: TreeNode[],
  headId: string | null,
  origForest: TreeNode[]
): { positions: Map<string, Pos>; edges: Edge[]; width: number; height: number } {
  const positions = new Map<string, Pos>();
  const edges: Edge[] = [];

  // 可见树 id → node（用于主干查找）
  const idToNode = new Map<string, TreeNode>();
  const walkMap = (ns: TreeNode[]) => ns.forEach((n) => { idToNode.set(n.id, n); walkMap(n.children); });
  walkMap(visibleForest);

  // 原始树 id → node（折叠后沿原始 parent 链回溯找最近可见祖先）
  const origIdToNode = new Map<string, TreeNode>();
  const walkOrig = (ns: TreeNode[]) => ns.forEach((n) => { origIdToNode.set(n.id, n); walkOrig(n.children); });
  walkOrig(origForest);

  // ── 主干目标：head；被折叠时取其最近可见祖先 ──
  let target: TreeNode | undefined = headId ? idToNode.get(headId) : undefined;
  if (!target && headId) {
    let cur: TreeNode | undefined = origIdToNode.get(headId);
    while (cur) {
      // 注意：必须取可见树的节点对象（orig 的节点带未折叠的 children，会泄漏隐藏子树）
      if (idToNode.has(cur.id)) {
        target = idToNode.get(cur.id);
        break;
      }
      cur = cur.parent_id ? origIdToNode.get(cur.parent_id) : undefined;
    }
  }

  // ── 主干：target → 根（target 可见则其祖先必然全部可见）──
  const spine: TreeNode[] = [];
  if (target) {
    let cur: TreeNode | undefined = target;
    while (cur) {
      spine.unshift(cur);
      cur = cur.parent_id ? idToNode.get(cur.parent_id) : undefined;
    }
  }
  const spineSet = new Set(spine.map((n) => n.id));
  const spineRootId = spine.length ? spine[0].id : null;

  spine.forEach((n, i) => {
    const parent = i > 0 ? spine[i - 1] : undefined;
    positions.set(n.id, {
      node: n,
      x: 0,
      y: i * ROW_H,
      isBranchStart: !parent || n.branch_id !== parent.branch_id,
    });
  });

  // ── 旁支组：主干节点的非主干孩子子树 + 非主干根（重新开局的其他会话）──
  const groups: Group[] = [];
  spine.forEach((n, i) => {
    const side = n.children.filter((c) => !spineSet.has(c.id));
    if (side.length > 0) groups.push(makeGroup(side, i + 1, n.branch_id));
  });
  for (const r of visibleForest) {
    if (r.id === spineRootId) continue;
    groups.push(makeGroup([r], 0, null));
  }

  // ── 轨道装箱：按起始深度排序，依次放入第一个行区间不冲突的轨道 ──
  groups.sort((a, b) => a.depthBase - b.depthBase);
  interface Track {
    width: number;
    spans: { start: number; end: number }[];
    groups: Group[];
  }
  const tracks: Track[] = [];
  for (const g of groups) {
    const span = { start: g.depthBase, end: g.depthBase + g.maxDepth };
    let track = tracks.find((t) => !t.spans.some((s) => !(span.end < s.start || span.start > s.end)));
    if (!track) {
      track = { width: 0, spans: [], groups: [] };
      tracks.push(track);
    }
    track.spans.push(span);
    track.width = Math.max(track.width, g.width);
    track.groups.push(g);
  }

  let trackX = NODE_W + BRANCH_GAP;
  for (const t of tracks) {
    for (const g of t.groups) {
      for (const e of g.entries) {
        positions.set(e.node.id, {
          node: e.node,
          x: trackX + e.center * SLOT_W - NODE_W / 2,
          y: (g.depthBase + e.depth) * ROW_H,
          isBranchStart: !e.parentBranchId || e.node.branch_id !== e.parentBranchId,
        });
      }
    }
    trackX += t.width * SLOT_W + BRANCH_GAP;
  }

  // ── 边：遍历可见树，父子均有位置时连线 ──
  const collectEdges = (ns: TreeNode[]) => {
    for (const n of ns) {
      const p = positions.get(n.id);
      if (!p) continue;
      for (const c of n.children) {
        const q = positions.get(c.id);
        if (q) {
          edges.push({ x1: p.x + NODE_W / 2, y1: p.y + NODE_H, x2: q.x + NODE_W / 2, y2: q.y });
        }
        collectEdges([c]);
      }
    }
  };
  collectEdges(visibleForest);

  // ── 尺寸 ──
  let width = Math.max(NODE_W, trackX - BRANCH_GAP);
  let height = NODE_H;
  for (const p of positions.values()) {
    height = Math.max(height, p.y + NODE_H);
  }
  return { positions, edges, width, height };
}

export default function TurnGraphPanel({ turns, selectedId, onSelect, error, currentId }: TurnGraphPanelProps) {
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());
  const [view, setView] = useState<View>({ x: 0, y: 0, scale: 1 });
  const containerRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ sx: number; sy: number; ox: number; oy: number; moved: boolean } | null>(null);
  const pendingHandlersRef = useRef<{ move: (e: PointerEvent) => void; up: () => void } | null>(null);
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

  const { positions, edges, width, height } = useMemo(
    () => layout(visible, currentId, forest),
    [visible, currentId, forest]
  );
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

  // 滚轮缩放（以光标为中心）。用 React 合成事件（与渲染周期同步、无挂载时机问题）；
  // 页面整体 overflow-hidden 不滚动，无需 preventDefault。
  const onWheel = (e: React.WheelEvent<HTMLDivElement>) => {
    userAdjustedRef.current = true;
    const rect = e.currentTarget.getBoundingClientRect();
    const cx = e.clientX - rect.left;
    const cy = e.clientY - rect.top;
    const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
    setView((v) => {
      const ns = Math.max(0.08, Math.min(3, v.scale * factor));
      const k = ns / v.scale;
      return { scale: ns, x: cx - (cx - v.x) * k, y: cy - (cy - v.y) * k };
    });
  };

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

  // 卸载时清理拖拽中的 window 级监听
  useEffect(() => () => {
    const h = pendingHandlersRef.current;
    if (h) {
      window.removeEventListener("pointermove", h.move);
      window.removeEventListener("pointerup", h.up);
      window.removeEventListener("pointercancel", h.up);
      pendingHandlersRef.current = null;
    }
  }, []);

  /**
   * 拖拽平移：pointerdown 时挂 window 级监听（而非容器级），
   * 这样拖出容器边界不会中断；不使用 setPointerCapture（会把 click 目标
   * 变成容器、吞掉节点/按钮点击）。文本选择由 select-none 禁止。
   */
  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    // 清理上次在窗口外释放残留的监听
    const pending = pendingHandlersRef.current;
    if (pending) {
      window.removeEventListener("pointermove", pending.move);
      window.removeEventListener("pointerup", pending.up);
      window.removeEventListener("pointercancel", pending.up);
      pendingHandlersRef.current = null;
    }
    dragRef.current = { sx: e.clientX, sy: e.clientY, ox: view.x, oy: view.y, moved: false };
    const el = e.currentTarget;
    const move = (ev: PointerEvent) => {
      const d = dragRef.current;
      if (!d) return;
      const dx = ev.clientX - d.sx;
      const dy = ev.clientY - d.sy;
      if (Math.abs(dx) + Math.abs(dy) > 4) {
        if (!d.moved) {
          d.moved = true;
          userAdjustedRef.current = true;
          el.style.cursor = "grabbing";
        }
        setView((v) => ({ ...v, x: d.ox + dx, y: d.oy + dy }));
      }
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
      pendingHandlersRef.current = null;
      el.style.cursor = "grab";
      dragRef.current = null;
    };
    pendingHandlersRef.current = { move, up };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
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
      className="relative flex-1 min-h-0 overflow-hidden rounded-lg border border-border bg-surface select-none"
      style={{
        // 点阵网格随视图平移缩放（Git graph 风格）
        backgroundImage: "radial-gradient(var(--color-border-val) 1px, transparent 1px)",
        backgroundSize: `${Math.max(10, 24 * view.scale)}px ${Math.max(10, 24 * view.scale)}px`,
        backgroundPosition: `${view.x}px ${view.y}px`,
        cursor: "grab",
        touchAction: "none",
      }}
      onPointerDown={onPointerDown}
      onWheel={onWheel}
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
                          title={isCollapsed ? `展开子树（${forkCount} 个子节点）` : `折叠子树（${forkCount} 个子节点）`}
                          onClick={(e) => { e.stopPropagation(); toggle(node.id); }}
                          className={`flex items-center shrink-0 gap-0.5 px-1.5 py-px rounded-full text-[10px] font-semibold leading-none cursor-pointer transition-colors ${
                            isCollapsed
                              ? "bg-primary text-white"
                              : "bg-surface-container-high text-muted-foreground hover:text-fg"
                          }`}
                        >
                          {isCollapsed ? (
                            <ChevronRight className="w-3 h-3" />
                          ) : (
                            <ChevronDown className="w-3 h-3" />
                          )}
                          {forkCount}
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
