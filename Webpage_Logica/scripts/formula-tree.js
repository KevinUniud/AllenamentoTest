/* Albero SVG deterministico derivato dal contratto construction.steps. */
(function exposeFormulaTree(global) {
    'use strict';
    const NS = 'http://www.w3.org/2000/svg';
    const MIN_CANVAS_WIDTH = 760;
    const CANVAS_PADDING = 36;
    const SIBLING_GAP = 44;
    const ROOT_GAP = 72;
    const LEVEL_GAP = 54;
    const NODE_MIN_WIDTH = 72;
    const NODE_LINE_HEIGHT = 16;
    const DEFAULT_MAX_LABEL_CHARS = 22;
    const OPERATOR_SYMBOLS = Object.freeze({ not: '¬', and: '∧', or: '∨', imp: '→', iff: '↔' });

    function toGraph(trace) {
        const steps = trace && Array.isArray(trace.steps) ? trace.steps : [];
        const nodes = steps.map(function(step) {
            return {
                id: String(step.node_id),
                label: String(step.result_prolog || step.operator || step.node_id),
                depth: Number(step.depth) || 0,
                step: step,
                operands: Array.isArray(step.operands) ? step.operands.map(String) : []
            };
        });
        const ids = new Set(nodes.map(function(node) { return node.id; }));
        const edges = [];
        nodes.forEach(function(node) {
            node.operands.forEach(function(operand, operandIndex) {
                if (ids.has(operand)) {
                    edges.push({ from: operand, to: node.id, operandIndex: operandIndex });
                }
            });
        });
        return { nodes: nodes, edges: edges };
    }

    function idSet(value) {
        if (value == null) return new Set();
        if (typeof value === 'string') return new Set([value]);
        try {
            return new Set(Array.from(value, String));
        } catch (_) {
            return new Set();
        }
    }

    function formatNodeLabel(node, options) {
        const fallback = node.label;
        const formatter = options && typeof options.formatFormula === 'function'
            ? options.formatFormula
            : null;
        if (!formatter) return fallback;
        try {
            return String(formatter(fallback) || fallback);
        } catch (_) {
            return fallback;
        }
    }

    function splitLabel(value, requestedLimit) {
        const text = String(value || '').trim();
        if (!text) return [''];
        const parsedLimit = Number(requestedLimit);
        const limit = Number.isInteger(parsedLimit) && parsedLimit >= 8
            ? parsedLimit
            : DEFAULT_MAX_LABEL_CHARS;
        const lines = [];
        let remaining = text.replace(/\s+/g, ' ');
        while (remaining.length > limit) {
            const candidate = remaining.slice(0, limit + 1);
            const spaceIndex = candidate.lastIndexOf(' ');
            const splitAt = spaceIndex >= Math.floor(limit / 2) ? spaceIndex : limit;
            lines.push(remaining.slice(0, splitAt).trimEnd());
            remaining = remaining.slice(splitAt).trimStart();
        }
        if (remaining || lines.length === 0) lines.push(remaining);
        return lines;
    }

    function measureNode(node, options) {
        const label = formatNodeLabel(node, options);
        if (!options || options.fullLabels !== true) {
            return {
                label: label,
                lines: [label.length > 11 ? label.slice(0, 10) + '…' : label],
                width: 56,
                height: 56,
                circular: true
            };
        }
        const lines = splitLabel(label, options && options.maxLabelChars);
        const longestLine = Math.max.apply(null, lines.map(function(line) { return Array.from(line).length; }));
        return {
            label: label,
            lines: lines,
            width: Math.max(NODE_MIN_WIDTH, longestLine * 7.5 + 28),
            height: Math.max(56, lines.length * NODE_LINE_HEIGHT + 24),
            circular: false
        };
    }

    function createLayout(graph, renderNodes) {
        const nodeById = new Map(graph.nodes.map(function(node) { return [node.id, node]; }));
        const referenced = new Set();
        graph.edges.forEach(function(edge) { referenced.add(edge.from); });
        let roots = graph.nodes.filter(function(node) { return !referenced.has(node.id); });
        if (roots.length === 0 && graph.nodes.length) roots = [graph.nodes[graph.nodes.length - 1]];

        const widthCache = new Map();
        function childIds(node, lineage) {
            return node.operands.filter(function(id) {
                return nodeById.has(id) && !lineage.has(id);
            });
        }
        function subtreeWidth(nodeId, lineage) {
            if (widthCache.has(nodeId)) return widthCache.get(nodeId);
            const node = nodeById.get(nodeId);
            if (!node) return 0;
            const nextLineage = new Set(lineage);
            nextLineage.add(nodeId);
            const children = childIds(node, nextLineage);
            const childrenWidth = children.reduce(function(total, childId, index) {
                return total + subtreeWidth(childId, nextLineage) + (index ? SIBLING_GAP : 0);
            }, 0);
            const width = Math.max(renderNodes.get(nodeId).width, childrenWidth);
            widthCache.set(nodeId, width);
            return width;
        }

        const rootWidths = roots.map(function(root) { return subtreeWidth(root.id, new Set()); });
        const forestWidth = rootWidths.reduce(function(total, width, index) {
            return total + width + (index ? ROOT_GAP : 0);
        }, 0);
        const width = Math.max(MIN_CANVAS_WIDTH, forestWidth + (CANVAS_PADDING * 2));
        const forestLeft = (width - forestWidth) / 2;
        const positions = new Map();

        function place(nodeId, left, treeWidth, depth, lineage) {
            const node = nodeById.get(nodeId);
            if (!node || lineage.has(nodeId)) return null;
            const nextLineage = new Set(lineage);
            nextLineage.add(nodeId);
            const children = childIds(node, nextLineage);
            const childWidths = children.map(function(childId) {
                return subtreeWidth(childId, nextLineage);
            });
            const childrenWidth = childWidths.reduce(function(total, childWidth, index) {
                return total + childWidth + (index ? SIBLING_GAP : 0);
            }, 0);
            let childLeft = left + ((treeWidth - childrenWidth) / 2);
            const childPositions = children.map(function(childId, index) {
                const childPosition = place(childId, childLeft, childWidths[index], depth + 1, nextLineage);
                childLeft += childWidths[index] + SIBLING_GAP;
                return childPosition;
            }).filter(Boolean);
            const x = childPositions.length
                ? (childPositions[0].x + childPositions[childPositions.length - 1].x) / 2
                : left + (treeWidth / 2);
            const position = { x: x, y: 0, depth: depth };
            positions.set(nodeId, position);
            return position;
        }

        let rootLeft = forestLeft;
        roots.forEach(function(root, index) {
            place(root.id, rootLeft, rootWidths[index], 0, new Set());
            rootLeft += rootWidths[index] + ROOT_GAP;
        });

        /* Una trace valida e un albero; questo fallback mantiene visibili anche nodi isolati o malformati. */
        graph.nodes.forEach(function(node) {
            if (positions.has(node.id)) return;
            const nodeWidth = subtreeWidth(node.id, new Set());
            place(node.id, rootLeft, nodeWidth, 0, new Set());
            rootLeft += nodeWidth + ROOT_GAP;
        });

        const levelHeights = [];
        positions.forEach(function(position, nodeId) {
            const height = renderNodes.get(nodeId).height;
            levelHeights[position.depth] = Math.max(levelHeights[position.depth] || 0, height);
        });
        const levelCenters = [];
        let verticalCursor = CANVAS_PADDING;
        levelHeights.forEach(function(levelHeight, depth) {
            levelCenters[depth] = verticalCursor + (levelHeight / 2);
            verticalCursor += levelHeight + LEVEL_GAP;
        });
        positions.forEach(function(position) {
            position.y = levelCenters[position.depth];
        });
        return {
            width: Math.max(width, rootLeft + CANVAS_PADDING - ROOT_GAP),
            height: Math.max(180, verticalCursor - LEVEL_GAP + CANVAS_PADDING),
            positions: positions
        };
    }

    function render(container, trace, options) {
        if (!container) return null;
        container.innerHTML = '';
        const graph = toGraph(trace);
        if (!graph.nodes.length) {
            container.textContent = 'Albero non disponibile per questa formula.';
            return null;
        }
        const settings = options || {};
        const selectedNodeIds = idSet(settings.selectedNodeIds);
        const availableRootIds = idSet(settings.availableRootIds);
        const onSelect = typeof settings.onSelect === 'function' ? settings.onSelect : null;
        const selectionMode = Boolean(onSelect) && settings.availableRootIds != null;
        const renderNodes = new Map(graph.nodes.map(function(node) {
            return [node.id, measureNode(node, settings)];
        }));
        const layout = createLayout(graph, renderNodes);
        const svg = document.createElementNS(NS, 'svg');
        svg.setAttribute('viewBox', '0 0 ' + layout.width + ' ' + layout.height);
        svg.setAttribute('width', String(layout.width));
        svg.setAttribute('height', String(layout.height));
        // I nodi sono controlli interattivi: role="img" renderebbe i discendenti
        // puramente presentazionali per le tecnologie assistive.
        svg.setAttribute('role', 'group');
        svg.setAttribute('aria-label', 'Albero di costruzione della formula, con ' + graph.nodes.length + ' nodi');
        svg.classList.add('chart-svg');
        graph.edges.forEach(function(edge) {
            const from = layout.positions.get(edge.from);
            const to = layout.positions.get(edge.to);
            if (!from || !to) return;
            const fromNode = renderNodes.get(edge.from);
            const toNode = renderNodes.get(edge.to);
            const line = document.createElementNS(NS, 'line');
            line.setAttribute('x1', String(from.x));
            line.setAttribute('y1', String(from.y - (fromNode.height / 2)));
            line.setAttribute('x2', String(to.x));
            line.setAttribute('y2', String(to.y + (toNode.height / 2)));
            line.setAttribute('class', 'formula-tree-edge');
            line.setAttribute('data-operand-index', String(edge.operandIndex));
            svg.appendChild(line);
        });
        graph.nodes.forEach(function(node) {
            const position = layout.positions.get(node.id);
            const rendered = renderNodes.get(node.id);
            const selectable = selectionMode && availableRootIds.has(node.id);
            const group = document.createElementNS(NS, 'g');
            if (!selectionMode || selectable) {
                group.setAttribute('tabindex', '0');
                group.setAttribute('role', 'button');
            } else {
                group.setAttribute('role', 'img');
                group.setAttribute('aria-disabled', 'true');
            }
            group.setAttribute('aria-label', 'Passaggio ' + node.step.index + ': ' + rendered.label);
            if (selectable) {
                group.setAttribute('aria-pressed', selectedNodeIds.has(node.id) ? 'true' : 'false');
            }
            group.setAttribute('data-node-id', node.id);
            group.setAttribute('data-node-kind', String(node.step.kind || ''));
            group.setAttribute('transform', 'translate(' + position.x + ' ' + position.y + ')');
            group.classList.add('formula-tree-group');
            if (selectedNodeIds.has(node.id)) group.classList.add('is-selected');
            if (availableRootIds.has(node.id)) group.classList.add('is-available');

            const shape = document.createElementNS(NS, rendered.circular ? 'circle' : 'rect');
            if (rendered.circular) {
                shape.setAttribute('cx', '0');
                shape.setAttribute('cy', '0');
                shape.setAttribute('r', '28');
            } else {
                shape.setAttribute('x', String(-(rendered.width / 2)));
                shape.setAttribute('y', String(-(rendered.height / 2)));
                shape.setAttribute('width', String(rendered.width));
                shape.setAttribute('height', String(rendered.height));
                shape.setAttribute('rx', String(Math.min(28, rendered.height / 2)));
                shape.setAttribute('ry', String(Math.min(28, rendered.height / 2)));
            }
            shape.setAttribute('class', 'formula-tree-node');
            const text = document.createElementNS(NS, 'text');
            text.setAttribute('x', '0');
            text.setAttribute('y', String(-((rendered.lines.length - 1) * NODE_LINE_HEIGHT) / 2 + 4));
            text.setAttribute('text-anchor', 'middle');
            text.setAttribute('class', 'formula-tree-label');
            text.setAttribute('data-full-label', rendered.label);
            rendered.lines.forEach(function(lineText, index) {
                const line = document.createElementNS(NS, 'tspan');
                line.setAttribute('x', '0');
                if (index) line.setAttribute('dy', String(NODE_LINE_HEIGHT));
                line.textContent = lineText;
                text.appendChild(line);
            });
            const select = function() {
                if (settings.detailElement) {
                    settings.detailElement.textContent = 'Passaggio ' + node.step.index + ': ' + rendered.label
                        + (node.step.operator ? '. Operatore: ' + (OPERATOR_SYMBOLS[node.step.operator] || node.step.operator) : '');
                }
                if (onSelect) onSelect(node);
            };
            if (!selectionMode || selectable) {
                group.addEventListener('click', select);
                group.addEventListener('keydown', function(event) {
                    if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        select();
                    }
                });
            }
            group.appendChild(shape);
            group.appendChild(text);
            svg.appendChild(group);
        });
        container.appendChild(svg);
        return graph;
    }

    global.LogicFormulaTree = Object.freeze({ render: render, toGraph: toGraph });
})(window);
