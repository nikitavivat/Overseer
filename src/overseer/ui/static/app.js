// Overseer UI. Pure browser JS, no build step.
// Talks to /api/* and /api/stream (WebSocket).

(() => {
  const $ = (id) => document.getElementById(id);
  const state = {
    activeRun: null,
    nodeStatus: {},          // node_id -> "pending"|"running"|"ok"|"fail"|"blocked"
    latestOutput: {},        // node_id -> output snapshot
    latestVerifier: {},      // node_id -> { verdict, score, reasons }
    selectedNode: null,
    runState: {},
    blockedNode: null,
    nodeStarts: {},          // node_id -> last node_started timestamp
    nodeDuration: {},        // node_id -> ms of last completion
    nodeAttempts: {},        // node_id -> attempt counter (resets on run_started)
    nodeFailures: {},        // node_id -> last failure error message
  };

  let cy = null;

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "content-type": "application/json" },
      ...opts,
    });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.json();
  }

  function nodeColor(status) {
    return {
      pending: "#4b5563",
      running: "#6aa0ff",
      ok: "#4ade80",
      fail: "#f87171",
      blocked: "#fbbf24",
    }[status] || "#4b5563";
  }

  function nodeLabel(id) {
    const status = state.nodeStatus[id] || "pending";
    const attempts = state.nodeAttempts[id] || 0;
    const dur = state.nodeDuration[id];
    const parts = [id];
    if (attempts > 1) parts.push(`×${attempts}`);
    if (dur != null && (status === "ok" || status === "fail")) {
      parts.push(`${formatMs(dur)}`);
    }
    return parts.join("  ");
  }

  function formatMs(ms) {
    if (ms < 1000) return `${Math.round(ms)}ms`;
    return `${(ms / 1000).toFixed(2)}s`;
  }

  function refreshNode(id) {
    if (!cy) return;
    const node = cy.getElementById(id);
    if (!node || !node.length) return;
    node.style("background-color", nodeColor(state.nodeStatus[id]));
    node.data("label", nodeLabel(id));
  }

  function buildGraph(topology) {
    $("process-name").textContent = topology.name;

    const elements = [];
    for (const n of topology.nodes) {
      elements.push({
        data: { id: n.id, label: n.id, kind: n.kind, model: n.model || "" },
      });
      state.nodeStatus[n.id] = "pending";
    }
    for (const e of topology.edges) {
      elements.push({
        data: {
          id: `${e.source}->${e.target}`,
          source: e.source,
          target: e.target,
          label: e.condition || "",
          policy: e.has_policy,
        },
      });
    }

    cy = cytoscape({
      container: $("graph"),
      elements,
      style: [
        {
          selector: "node",
          style: {
            shape: "round-rectangle",
            "background-color": (ele) => nodeColor(state.nodeStatus[ele.id()] || "pending"),
            "border-width": 2,
            "border-color": "#232c3a",
            "color": "#e6edf3",
            "label": "data(label)",
            "text-valign": "center",
            "text-halign": "center",
            "font-family": "ui-monospace, monospace",
            "font-size": 12,
            "padding": "12px",
            "width": "label",
            "height": "label",
            "text-wrap": "wrap",
            "text-max-width": 160,
          },
        },
        {
          selector: 'node[kind="verifier"]',
          style: { shape: "diamond", "padding": "18px" },
        },
        {
          selector: 'node[kind="terminal"]',
          style: { "background-color": "#1a212c", "border-style": "dashed" },
        },
        {
          selector: "node:selected",
          style: { "border-color": "#e6edf3", "border-width": 3 },
        },
        {
          selector: "edge",
          style: {
            width: 1.5,
            "line-color": "#3a4655",
            "target-arrow-color": "#3a4655",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            "label": "data(label)",
            "font-size": 10,
            "color": "#8b96a6",
            "text-background-color": "#0c1014",
            "text-background-opacity": 1,
            "text-background-padding": 2,
          },
        },
        {
          selector: 'edge[label="fail"]',
          style: { "line-color": "#f87171", "target-arrow-color": "#f87171" },
        },
        {
          selector: 'edge[label="pass"]',
          style: { "line-color": "#4ade80", "target-arrow-color": "#4ade80" },
        },
      ],
      layout: { name: "dagre", rankDir: "LR", nodeSep: 60, rankSep: 100 },
    });

    cy.on("tap", "node", (evt) => {
      const id = evt.target.id();
      if (id === "end") return;
      openDrawer(id);
    });
  }

  function setStatusPill(status) {
    const pill = $("status-pill");
    pill.textContent = status;
    pill.className = `pill ${status}`;
  }

  function pushEvent(event) {
    const li = document.createElement("li");
    li.className = `t-${event.type}`;
    const t = new Date(event.timestamp * 1000).toLocaleTimeString();
    const node = event.node_id ? `<span class="node">[${event.node_id}]</span> ` : "";
    const hasPayload = event.payload && Object.keys(event.payload).length > 0;
    li.innerHTML = `
      <div class="event-row">
        <span class="event-time">${t}</span>
        ${node}${event.type}
        ${hasPayload ? '<span class="chev">▸</span>' : ""}
      </div>
      ${hasPayload ? `<pre class="event-payload hidden">${escapeHtml(JSON.stringify(event.payload, null, 2))}</pre>` : ""}
    `;
    if (hasPayload) {
      li.querySelector(".event-row").addEventListener("click", () => {
        const pre = li.querySelector(".event-payload");
        const chev = li.querySelector(".chev");
        pre.classList.toggle("hidden");
        chev.textContent = pre.classList.contains("hidden") ? "▸" : "▾";
      });
    }
    const list = $("event-list");
    list.prepend(li);
    while (list.children.length > 200) list.removeChild(list.lastChild);
  }

  function escapeHtml(s) {
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function resetRunUI() {
    Object.keys(state.nodeStatus).forEach((id) => {
      state.nodeStatus[id] = "pending";
      state.nodeAttempts[id] = 0;
      state.nodeDuration[id] = null;
    });
    state.nodeStarts = {};
    state.latestOutput = {};
    state.latestVerifier = {};
    state.nodeFailures = {};
    state.blockedNode = null;
    Object.keys(state.nodeStatus).forEach(refreshNode);
  }

  function applyEvent(event) {
    pushEvent(event);

    if (event.run_id !== state.activeRun) return;

    switch (event.type) {
      case "run_started":
        resetRunUI();
        setStatusPill("running");
        break;
      case "node_started":
        if (event.node_id) {
          state.nodeStatus[event.node_id] = "running";
          state.nodeStarts[event.node_id] = event.timestamp;
          state.nodeAttempts[event.node_id] = (state.nodeAttempts[event.node_id] || 0) + 1;
          refreshNode(event.node_id);
        }
        break;
      case "node_completed":
        if (event.node_id) {
          state.nodeStatus[event.node_id] = "ok";
          state.latestOutput[event.node_id] = event.payload?.output;
          if (state.nodeStarts[event.node_id] != null) {
            state.nodeDuration[event.node_id] = (event.timestamp - state.nodeStarts[event.node_id]) * 1000;
          }
          refreshNode(event.node_id);
        }
        break;
      case "node_failed":
        if (event.node_id) {
          state.nodeStatus[event.node_id] = "fail";
          state.nodeFailures[event.node_id] = event.payload?.error || "";
          if (state.nodeStarts[event.node_id] != null) {
            state.nodeDuration[event.node_id] = (event.timestamp - state.nodeStarts[event.node_id]) * 1000;
          }
          refreshNode(event.node_id);
        }
        break;
      case "verifier_pass":
        if (event.node_id) {
          state.latestVerifier[event.node_id] = { verdict: "pass", ...event.payload };
        }
        break;
      case "verifier_fail":
        if (event.node_id) {
          state.latestVerifier[event.node_id] = { verdict: "fail", ...event.payload };
        }
        break;
      case "node_blocked":
      case "run_blocked": {
        const target = event.payload?.blocked_node || event.node_id;
        if (target) {
          state.blockedNode = target;
          state.nodeStatus[target] = "blocked";
          refreshNode(target);
        }
        setStatusPill("blocked");
        if (state.blockedNode) openDrawer(state.blockedNode);
        break;
      }
      case "run_resumed":
        setStatusPill("running");
        if (state.blockedNode) {
          state.nodeStatus[state.blockedNode] = "running";
          refreshNode(state.blockedNode);
        }
        state.blockedNode = null;
        break;
      case "run_completed":
        setStatusPill("ok");
        state.runState = event.payload?.state || {};
        renderStateSummary();
        break;
      case "run_failed":
        setStatusPill("fail");
        break;
      case "run_aborted":
        setStatusPill("idle");
        break;
    }
  }

  function renderStateSummary() {
    const el = $("state-summary");
    if (!Object.keys(state.runState).length) {
      el.textContent = "no state yet";
      return;
    }
    el.textContent = JSON.stringify(state.runState, null, 2);
  }

  async function openDrawer(nodeId) {
    state.selectedNode = nodeId;
    $("drawer").classList.remove("hidden");
    $("drawer-title").textContent = nodeId;

    const status = state.nodeStatus[nodeId] || "pending";
    const attempts = state.nodeAttempts[nodeId] || 0;
    const dur = state.nodeDuration[nodeId];
    const statusBits = [`<span class="pill ${status}">${status}</span>`];
    if (attempts > 1) statusBits.push(`attempts: ${attempts}`);
    if (dur != null) statusBits.push(`last: ${formatMs(dur)}`);
    $("drawer-status").innerHTML = statusBits.join("  ·  ");

    const output = state.latestOutput[nodeId];
    $("drawer-output").textContent = output ? JSON.stringify(output, null, 2) : "—";

    const failure = state.nodeFailures[nodeId];
    const failEl = $("drawer-failure");
    if (failure) {
      failEl.parentElement.classList.remove("hidden");
      failEl.textContent = failure;
    } else {
      failEl.parentElement.classList.add("hidden");
    }

    const v = state.latestVerifier[nodeId];
    if (v) {
      const reasons = (v.reasons || []).map((r) => "  • " + r).join("\n");
      $("drawer-verdict").textContent =
        `${v.verdict}${v.score != null ? ` (score=${v.score})` : ""}\n${reasons}`;
    } else {
      $("drawer-verdict").textContent = "—";
    }

    $("override-prompt").value = "";
    $("intervene-result").textContent = "";

    if (state.activeRun) loadSnapshotsForNode(state.activeRun, nodeId);
  }

  async function loadSnapshotsForNode(runId, nodeId) {
    const list = $("snapshot-list");
    list.innerHTML = '<li class="muted">loading…</li>';
    try {
      const snaps = await api(`/api/runs/${runId}/snapshots`);
      const filtered = snaps.filter((s) => s.node_id === nodeId);
      list.innerHTML = "";
      if (!filtered.length) {
        list.innerHTML = '<li class="muted">no snapshots yet</li>';
        return;
      }
      filtered.forEach((s, i) => {
        const li = document.createElement("li");
        const t = new Date(s.timestamp * 1000).toLocaleTimeString();
        li.innerHTML = `
          <div class="snap-row">
            <span class="snap-idx">#${i + 1}</span>
            <span class="snap-id">${s.snapshot_id.slice(0, 8)}</span>
            <span class="snap-time">${t}</span>
            <span class="chev">▸</span>
          </div>
          <pre class="snap-body hidden">${escapeHtml(JSON.stringify(s.data, null, 2))}</pre>
        `;
        li.querySelector(".snap-row").addEventListener("click", () => {
          const body = li.querySelector(".snap-body");
          const chev = li.querySelector(".chev");
          body.classList.toggle("hidden");
          chev.textContent = body.classList.contains("hidden") ? "▸" : "▾";
        });
        list.appendChild(li);
      });
    } catch (e) {
      list.innerHTML = `<li class="muted">load failed: ${e}</li>`;
    }
  }

  function closeDrawer() {
    $("drawer").classList.add("hidden");
    state.selectedNode = null;
  }

  async function intervene(action) {
    if (!state.activeRun) {
      $("intervene-result").textContent = "no active run";
      return;
    }
    const overrides = {};
    const promptText = $("override-prompt").value.trim();
    if (promptText) overrides.prompt = promptText;
    try {
      await api(`/api/runs/${state.activeRun}/intervene`, {
        method: "POST",
        body: JSON.stringify({
          action,
          node: state.selectedNode || state.blockedNode,
          overrides,
        }),
      });
      $("intervene-result").textContent = `${action} submitted`;
    } catch (e) {
      $("intervene-result").textContent = String(e);
    }
  }

  async function startRun() {
    const task = $("task-input").value.trim() || "Demo task";
    const res = await api("/api/runs", {
      method: "POST",
      body: JSON.stringify({ inputs: { task } }),
    });
    state.activeRun = res.run_id;
    setStatusPill("running");
    state.runState = {};
    resetRunUI();
    refreshRuns();
  }

  async function refreshRuns() {
    const runs = await api("/api/runs");
    const list = $("run-list");
    list.innerHTML = "";
    for (const r of runs) {
      const li = document.createElement("li");
      if (r.run_id === state.activeRun) li.classList.add("active");
      const dur = r.ended_at ? formatMs((r.ended_at - r.started_at) * 1000) : "";
      li.innerHTML = `
        ${r.run_id.slice(0, 8)}
        <span class="status ${r.status}">${r.status}</span>
        <span class="run-dur">${dur}</span>
      `;
      li.onclick = () => selectRun(r.run_id);
      list.appendChild(li);
    }
  }

  async function selectRun(runId) {
    state.activeRun = runId;
    refreshRuns();
    resetRunUI();
    const events = await api(`/api/runs/${runId}/events`);
    $("event-list").innerHTML = "";
    for (const e of events) applyEvent(e);
    const run = await api(`/api/runs/${runId}`);
    state.runState = run.state || {};
    renderStateSummary();
  }

  function connectStream() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${location.host}/api/stream`);
    ws.onmessage = (msg) => {
      const event = JSON.parse(msg.data);
      applyEvent(event);
      if (event.type === "run_started" || event.type === "run_completed" || event.type === "run_failed") {
        refreshRuns();
      }
    };
    ws.onclose = () => setTimeout(connectStream, 1500);
  }

  async function bootstrap() {
    const topology = await api("/api/graph");
    buildGraph(topology);
    connectStream();
    await refreshRuns();
  }

  $("start-btn").addEventListener("click", startRun);
  $("drawer-close").addEventListener("click", closeDrawer);
  $("retry-btn").addEventListener("click", () => intervene("retry"));
  $("skip-btn").addEventListener("click", () => intervene("skip"));
  $("abort-btn").addEventListener("click", () => intervene("abort"));

  bootstrap().catch((e) => console.error("bootstrap failed", e));
})();
