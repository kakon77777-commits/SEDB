const state = { viewId: null, fieldOffset: 0, fieldLimit: 12 };

async function api(path, options = {}) {
  const config = { ...options, headers: { ...(options.headers || {}) } };
  if (config.body && typeof config.body !== 'string') {
    config.headers['Content-Type'] = 'application/json';
    config.body = JSON.stringify(config.body);
  }
  const response = await fetch(path, config);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function toast(message, error = false) {
  const el = document.getElementById('toast');
  el.textContent = message;
  el.className = error ? 'show error' : 'show';
  setTimeout(() => el.className = '', 2600);
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}

async function loadStats() {
  const s = await api('/api/stats');
  const items = [
    ['Fields', s.fields], ['Active', s.active_fields], ['Converged', s.converged_fields],
    ['Entities', s.entities], ['Sparse Cells', s.cells], ['Views', s.views],
    ['Logical Capacity', s.logical_capacity], ['Density', `${(s.density * 100).toFixed(5)}%`]
  ];
  document.getElementById('stats').innerHTML = items.map(([k,v]) => `<div><strong>${esc(v)}</strong><span>${esc(k)}</span></div>`).join('');
}

async function loadFields() {
  const q = document.getElementById('fieldSearch').value.trim();
  const rows = await api(`/api/fields?limit=200&search=${encodeURIComponent(q)}`);
  const list = document.getElementById('fieldList');
  list.innerHTML = rows.map(f => {
    const action = f.status === 'active' ? 'converge' : (f.status === 'converged' ? 'reactivate' : '');
    return `<div class="item">
      <div><code>${esc(f.key)}</code><strong>${esc(f.label)}</strong><small>${esc(f.namespace || 'global')} · ${esc(f.value_type)} · ${esc(f.status)}</small></div>
      ${action ? `<button data-field="${esc(f.id)}" data-action="${action}">${action === 'converge' ? '收斂' : '重新啟用'}</button>` : ''}
    </div>`;
  }).join('') || '<div class="empty">沒有欄位</div>';
  list.querySelectorAll('button[data-field]').forEach(button => button.addEventListener('click', async () => {
    const action = button.dataset.action;
    const reason = prompt(action === 'converge' ? '收斂原因（必填）' : '重新啟用原因（必填）');
    if (!reason) return;
    const to_status = action === 'converge' ? 'converged' : 'active';
    try {
      await api(`/api/fields/${button.dataset.field}/transition`, {method:'POST', body:{to_status, reason, evaluator:'browser:user'}});
      toast('欄位狀態已更新');
      await refreshAll();
    } catch (e) { toast(e.message, true); }
  }));
}

async function loadProposals() {
  const rows = await api('/api/proposals?limit=200');
  const pending = rows.filter(p => p.status === 'pending');
  const list = document.getElementById('proposalList');
  list.innerHTML = pending.map(p => `<div class="item">
    <div><code>${esc(p.key)}</code><strong>${esc(p.label)}</strong><small>${esc(p.namespace || 'global')} · ${esc(p.reason)}</small></div>
    <div class="actions">
      <button data-score="${esc(p.id)}">Score</button>
      <button data-proposal="${esc(p.id)}" data-decision="accept">接受</button>
      <button data-proposal="${esc(p.id)}" data-decision="reject">拒絕</button>
    </div>
  </div>`).join('') || '<div class="empty">沒有 pending proposal</div>';

  list.querySelectorAll('button[data-score]').forEach(button => button.addEventListener('click', async () => {
    try {
      const rows = await api(`/api/proposals/${button.dataset.score}/candidates`, {
        method:'POST', body:{top_k:8, max_candidates:500}
      });
      toast(`Score 完成：${rows.length} candidates`);
      await loadSemanticCandidates();
    } catch (e) { toast(e.message, true); }
  }));

  list.querySelectorAll('button[data-proposal]').forEach(button => button.addEventListener('click', async () => {
    const decision = button.dataset.decision;
    const reason = prompt(decision === 'accept' ? '接受理由（必填）' : '拒絕理由（必填）');
    if (!reason) return;
    try {
      const result = await api(`/api/proposals/${button.dataset.proposal}/decision`, {
        method:'POST', body:{decision, reason, evaluator:'browser:user'}
      });
      toast(decision === 'accept' ? `Proposal 已接受：${result.outcome}` : 'Proposal 已拒絕');
      await refreshAll();
    } catch (e) { toast(e.message, true); }
  }));
}

async function loadSemanticCandidates() {
  const rows = await api('/api/candidates?status=pending&limit=200');
  const list = document.getElementById('semanticCandidateList');
  list.innerHTML = rows.map(c => {
    const score = Number(c.score || 0).toFixed(4);
    const decisions = c.source_kind === 'proposal'
      ? [['alias','Alias'],['distinct','Distinct'],['ignore','Ignore']]
      : [['related','Related'],['distinct','Distinct'],['ignore','Ignore']];
    return `<div class="item">
      <div><code>${esc(c.source_kind)}:${esc(c.source_ref)}</code><strong>→ ${esc(c.candidate_field_id)}</strong><small>score ${esc(score)} · key ${esc(c.signals?.key ?? '')} · label ${esc(c.signals?.label ?? '')}</small></div>
      <div class="actions">${decisions.map(([d,label]) => `<button data-candidate="${esc(c.id)}" data-review="${esc(d)}">${esc(label)}</button>`).join('')}</div>
    </div>`;
  }).join('') || '<div class="empty">沒有 pending semantic candidate</div>';
  list.querySelectorAll('button[data-candidate]').forEach(button => button.addEventListener('click', async () => {
    const reason = prompt(`${button.dataset.review} 理由（必填）`);
    if (!reason) return;
    try {
      await api(`/api/candidates/${button.dataset.candidate}/review`, {
        method:'POST', body:{decision:button.dataset.review, reason, evaluator:'browser:user'}
      });
      toast(`Candidate 已 review：${button.dataset.review}`);
      await refreshAll();
    } catch (e) { toast(e.message, true); }
  }));
}

async function loadEntities() {
  const rows = await api('/api/entities?limit=500');
  document.getElementById('entityList').innerHTML = rows.map(e =>
    `<div class="item"><div><strong>${esc(e.label)}</strong><small>${esc(e.kind)} · ${esc(e.id)}</small></div></div>`
  ).join('') || '<div class="empty">沒有 Entity</div>';
}

async function loadViews() {
  const rows = await api('/api/views');
  const select = document.getElementById('viewSelect');
  const previous = state.viewId;
  select.innerHTML = rows.map(v => `<option value="${esc(v.id)}">${esc(v.name)} (${v.field_count})</option>`).join('');
  if (rows.length) {
    state.viewId = rows.some(v => v.id === previous) ? previous : rows[0].id;
    select.value = state.viewId;
  } else {
    state.viewId = null;
  }
}

function displayValue(value) {
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}

async function loadMatrix() {
  const table = document.getElementById('matrix');
  if (!state.viewId) {
    table.innerHTML = '<tr><td class="empty">先建立 Task View</td></tr>';
    document.getElementById('windowInfo').textContent = '';
    return;
  }
  const m = await api(`/api/views/${state.viewId}?field_offset=${state.fieldOffset}&field_limit=${state.fieldLimit}`);
  const head = `<tr><th>Entity</th>${m.fields.map(f => `<th title="${esc(f.label)}">${esc(f.key)}</th>`).join('')}</tr>`;
  const body = m.rows.map(row => `<tr><th>${esc(row.label)}</th>${m.fields.map(f => {
    const present = Object.prototype.hasOwnProperty.call(row.values, f.key);
    const text = present ? displayValue(row.values[f.key]) : '';
    return `<td><button class="cell ${present ? 'present' : 'blank'}" data-entity="${esc(row.id)}" data-field="${esc(f.key)}" data-present="${present ? '1' : '0'}">${present ? esc(text) : '∅'}</button></td>`;
  }).join('')}</tr>`).join('');
  table.innerHTML = head + body;
  document.getElementById('windowInfo').textContent = `${m.field_offset + 1}–${Math.min(m.total_fields, m.field_offset + m.fields.length)} / ${m.total_fields}`;
  table.querySelectorAll('button.cell').forEach(button => button.addEventListener('click', async () => {
    const present = button.dataset.present === '1';
    const promptText = present ? '輸入 JSON 值；留空並確認會刪除此 cell' : '輸入 JSON 值（字串請加雙引號）';
    const raw = prompt(promptText, present ? button.textContent : '');
    if (raw === null) return;
    try {
      if (raw === '' && present) {
        await api(`/api/entities/${button.dataset.entity}/cells/${encodeURIComponent(button.dataset.field)}`, {method:'DELETE'});
      } else {
        let value;
        try { value = JSON.parse(raw); } catch { value = raw; }
        await api(`/api/entities/${button.dataset.entity}/cells/${encodeURIComponent(button.dataset.field)}`, {method:'PUT', body:{value, source:'browser:user'}});
      }
      await loadMatrix(); await loadStats();
    } catch (e) { toast(e.message, true); }
  }));
}


async function loadFamilyProposals() {
  const rows = await api('/api/family-proposals?limit=100');
  const list = document.getElementById('familyProposalList');
  list.innerHTML = rows.map(p => {
    const names = (p.members || []).map(m => m.key).join(', ');
    const reviewed = !!p.review;
    return `<div class="item">
      <div><code>${esc(p.id.slice(0,8))}</code><strong>${p.member_count} members</strong><small>${esc(names)} · min ${Number(p.min_pair_score).toFixed(3)} · avg ${Number(p.avg_pair_score).toFixed(3)}</small></div>
      <div class="actions">${reviewed ? `<span>${esc(p.review.decision)}</span>` : `
        <button data-family-review="duplicate_family" data-proposal="${esc(p.id)}">Duplicate</button>
        <button data-family-review="related_family" data-proposal="${esc(p.id)}">Related</button>
        <button data-family-review="reject" data-proposal="${esc(p.id)}">Reject</button>`}</div>
    </div>`;
  }).join('') || '<div class="empty">尚無 family proposal</div>';
  list.querySelectorAll('button[data-family-review]').forEach(button => button.addEventListener('click', async () => {
    const reason = document.getElementById('familyReviewReason').value.trim();
    if (!reason) { toast('Family review reason 必填', true); return; }
    try {
      await api(`/api/family-proposals/${button.dataset.proposal}/review`, {
        method:'POST', body:{decision:button.dataset.familyReview, reason, evaluator:'browser:user'}
      });
      toast(`Family review: ${button.dataset.familyReview}`);
      await Promise.all([loadFamilyProposals(), loadFieldFamilies()]);
    } catch (e) { toast(e.message, true); }
  }));
}

async function loadFieldFamilies() {
  const rows = await api('/api/field-families?limit=100');
  const list = document.getElementById('fieldFamilyList');
  list.innerHTML = rows.map(f => `<div class="item"><div><code>${esc(f.family_type)}</code><strong>${esc(f.label)}</strong><small>${(f.members || []).map(m => esc(m.key)).join(', ')}</small></div></div>`).join('') || '<div class="empty">尚無 confirmed family</div>';
}

async function refreshAll() {
  try {
    await Promise.all([loadStats(), loadFields(), loadEntities(), loadProposals(), loadSemanticCandidates(), loadFamilyProposals(), loadFieldFamilies(), loadAgentRuns(), loadCampaigns()]);
    await loadViews();
    await loadMatrix();
  } catch (e) { toast(e.message, true); }
}

document.getElementById('fieldForm').addEventListener('submit', async event => {
  event.preventDefault(); const form = new FormData(event.currentTarget);
  try {
    await api('/api/fields', {method:'POST', body:Object.fromEntries(form.entries())});
    event.currentTarget.reset(); toast('欄位已新增'); await refreshAll();
  } catch (e) { toast(e.message, true); }
});

document.getElementById('proposalForm').addEventListener('submit', async event => {
  event.preventDefault(); const form = new FormData(event.currentTarget);
  try {
    await api('/api/proposals', {method:'POST', body:Object.fromEntries(form.entries())});
    event.currentTarget.reset();
    event.currentTarget.elements.namespace.value = 'global';
    event.currentTarget.elements.proposed_by.value = 'browser:user';
    toast('Proposal 已建立'); await refreshAll();
  } catch (e) { toast(e.message, true); }
});

document.getElementById('entityForm').addEventListener('submit', async event => {
  event.preventDefault(); const form = new FormData(event.currentTarget);
  try {
    await api('/api/entities', {method:'POST', body:Object.fromEntries(form.entries())});
    event.currentTarget.reset(); toast('Entity 已新增'); await refreshAll();
  } catch (e) { toast(e.message, true); }
});

document.getElementById('viewForm').addEventListener('submit', async event => {
  event.preventDefault(); const form = new FormData(event.currentTarget);
  const field_keys = String(form.get('field_keys') || '').split(',').map(x => x.trim()).filter(Boolean);
  try {
    const view = await api('/api/views', {method:'POST', body:{name:form.get('name'), field_keys}});
    state.viewId = view.id; state.fieldOffset = 0; toast('Task View 已建立'); await loadViews(); await loadMatrix(); await loadStats();
  } catch (e) { toast(e.message, true); }
});

document.getElementById('fieldSearchBtn').addEventListener('click', loadFields);
document.getElementById('fieldSearch').addEventListener('keydown', e => { if (e.key === 'Enter') loadFields(); });
document.getElementById('refreshAll').addEventListener('click', refreshAll);
document.getElementById('loadView').addEventListener('click', () => { state.viewId = document.getElementById('viewSelect').value; state.fieldOffset = 0; loadMatrix(); });
document.getElementById('viewSelect').addEventListener('change', e => { state.viewId = e.target.value; state.fieldOffset = 0; });
document.getElementById('prevFields').addEventListener('click', () => { state.fieldOffset = Math.max(0, state.fieldOffset - state.fieldLimit); loadMatrix(); });
document.getElementById('nextFields').addEventListener('click', () => { state.fieldOffset += state.fieldLimit; loadMatrix(); });
document.getElementById('scanSimilarity').addEventListener('click', async () => {
  try {
    const rows = await api('/api/governance/similarity/scan', {
      method:'POST', body:{namespace:'global', threshold:0.72, max_neighbors:12}
    });
    toast(`Registry scan：${rows.length} candidates`);
    await loadSemanticCandidates();
  } catch (e) { toast(e.message, true); }
});

document.getElementById('globalSearchBtn').addEventListener('click', async () => {
  try {
    const q = document.getElementById('globalSearch').value.trim();
    const data = await api(`/api/search?q=${encodeURIComponent(q)}`);
    document.getElementById('searchResults').textContent = JSON.stringify(data, null, 2);
  } catch (e) { toast(e.message, true); }
});

document.getElementById('familyGenerateBtn').addEventListener('click', async () => {
  const seed_ref = document.getElementById('familySeedRef').value.trim();
  if (!seed_ref) { toast('請輸入 seed field reference', true); return; }
  try {
    const result = await api('/api/family-proposals/generate', {
      method:'POST', body:{seed_ref, seed_threshold:0.78, min_coherence:0.72, max_neighbors:24, max_members:8, namespace:'global', evaluator:'browser:user'}
    });
    toast(result ? `Family proposal: ${result.member_count} members` : '沒有形成 coherent family');
    await loadFamilyProposals();
  } catch (e) { toast(e.message, true); }
});

document.getElementById('familyRegistryScanBtn').addEventListener('click', async () => {
  try {
    const rows = await api('/api/family-proposals/scan', {
      method:'POST', body:{namespace:'global', seed_threshold:0.78, min_coherence:0.72, max_neighbors:12, max_members:8, limit_fields:1000, max_proposals:100, evaluator:'browser:user'}
    });
    toast(`Family scan: ${rows.length} proposals`);
    await loadFamilyProposals();
  } catch (e) { toast(e.message, true); }
});

refreshAll();

async function loadUtilityState(fieldRef) {
  const ref = String(fieldRef || document.getElementById('utilityFieldRef').value || '').trim();
  if (!ref) {
    document.getElementById('utilityAssessmentList').innerHTML = '<div class="empty">輸入 field id / key / alias</div>';
    document.getElementById('utilityGuardrailState').textContent = '';
    return;
  }
  const [assessments, guardrail] = await Promise.all([
    api(`/api/fields/${encodeURIComponent(ref)}/utility/assessments?limit=100`),
    api(`/api/fields/${encodeURIComponent(ref)}/guardrail`),
  ]);
  document.getElementById('utilityGuardrailState').textContent = guardrail
    ? `Guardrail: ${guardrail.protected ? 'PROTECTED' : 'unprotected'} · ${guardrail.reason}`
    : 'Guardrail: none';
  const list = document.getElementById('utilityAssessmentList');
  list.innerHTML = assessments.slice().reverse().map(a => {
    const actionable = a.recommendation === 'converge_candidate' || a.recommendation === 'reactivate_candidate';
    const metrics = a.metrics || {};
    return `<div class="item">
      <div><code>${esc(a.recommendation)}</code><strong>U=${Number(a.score || 0).toFixed(4)}</strong><small>${esc(a.reason)} · coverage ${esc(metrics.coverage ?? '')} · task ${esc(metrics.task_support ?? '')} · redundancy ${esc(metrics.semantic_redundancy ?? '')}</small></div>
      <div class="actions">${actionable ? `<button data-utility-apply="${esc(a.id)}">Apply</button>` : ''}</div>
    </div>`;
  }).join('') || '<div class="empty">尚無 utility assessment</div>';
  list.querySelectorAll('button[data-utility-apply]').forEach(button => button.addEventListener('click', async () => {
    const reason = document.getElementById('utilityApplyReason').value.trim();
    if (!reason) { toast('Apply reason 必填', true); return; }
    try {
      const result = await api(`/api/utility/assessments/${button.dataset.utilityApply}/apply`, {
        method:'POST', body:{reason, evaluator:'browser:user'}
      });
      toast(`Utility recommendation 已套用：${result.field.status}`);
      await refreshAll();
      await loadUtilityState(ref);
    } catch (e) { toast(e.message, true); }
  }));
}

document.getElementById('utilityAssessBtn').addEventListener('click', async () => {
  const ref = document.getElementById('utilityFieldRef').value.trim();
  if (!ref) { toast('請輸入 field reference', true); return; }
  try {
    const result = await api(`/api/fields/${encodeURIComponent(ref)}/utility/assess`, {
      method:'POST', body:{evaluator:'browser:user'}
    });
    toast(`Assessment：${result.recommendation}`);
    await loadUtilityState(ref);
  } catch (e) { toast(e.message, true); }
});

async function setUtilityGuardrail(protectedState) {
  const ref = document.getElementById('utilityFieldRef').value.trim();
  const reason = document.getElementById('utilityGuardrailReason').value.trim();
  if (!ref || !reason) { toast('field reference 與 guardrail reason 必填', true); return; }
  try {
    await api(`/api/fields/${encodeURIComponent(ref)}/guardrail`, {
      method:'POST', body:{protected:protectedState, reason, evaluator:'browser:user'}
    });
    toast(protectedState ? 'Field 已保護' : 'Field 已解除保護');
    await loadUtilityState(ref);
  } catch (e) { toast(e.message, true); }
}

document.getElementById('utilityProtectBtn').addEventListener('click', () => setUtilityGuardrail(true));
document.getElementById('utilityUnprotectBtn').addEventListener('click', () => setUtilityGuardrail(false));
document.getElementById('utilityRegistryScan').addEventListener('click', async () => {
  try {
    const rows = await api('/api/governance/utility/scan', {
      method:'POST', body:{statuses:['active','converged'], limit_fields:1000, evaluator:'browser:user'}
    });
    toast(`Utility scan：${rows.length} assessments`);
    const ref = document.getElementById('utilityFieldRef').value.trim();
    if (ref) await loadUtilityState(ref);
  } catch (e) { toast(e.message, true); }
});


async function loadAgentRuns() {
  const rows = await api('/api/agent/runs?limit=50');
  const list = document.getElementById('agentRunList');
  if (!list) return;
  list.innerHTML = rows.map(run => `<div class="item"><div><code>${esc(run.status)}</code><strong>${esc(run.backend)}</strong><small>${esc(run.id)} · steps ${esc((run.counters || {}).steps ?? 0)}</small></div><div class="actions"><button data-agent-run-detail="${esc(run.id)}">Receipts</button></div></div>`).join('') || '<div class="empty">尚無 Agent run</div>';
  list.querySelectorAll('button[data-agent-run-detail]').forEach(button => button.addEventListener('click', async () => {
    try {
      const detail = await api(`/api/agent/runs/${encodeURIComponent(button.dataset.agentRunDetail)}`);
      document.getElementById('agentRunDetail').textContent = JSON.stringify({
        id: detail.id,
        status: detail.status,
        backend: detail.backend,
        budget: detail.budget,
        counters: detail.counters,
        events: detail.events,
        actions: detail.actions,
      }, null, 2);
    } catch (e) { toast(e.message, true); }
  }));
}

async function runAgent(endpoint, inputId, external=false) {
  try {
    const value = JSON.parse(document.getElementById(inputId).value || '{}');
    const body = external
      ? {packet:value, evaluator:'browser:external-agent'}
      : {observation:value, evaluator:'browser:agent'};
    const run = await api(endpoint, {method:'POST', body});
    document.getElementById('agentRunDetail').textContent = JSON.stringify({
      id: run.id,
      status: run.status,
      backend: run.backend,
      budget: run.budget,
      counters: run.counters,
      events: run.events,
      actions: run.actions,
    }, null, 2);
    toast(`Agent run: ${run.status}`);
    await Promise.all([loadAgentRuns(), loadProposals(), loadSemanticCandidates(), loadFamilyProposals()]);
  } catch (e) { toast(e.message, true); }
}

const deterministicAgentButton = document.getElementById('agentRunDeterministic');
if (deterministicAgentButton) deterministicAgentButton.addEventListener('click', () => runAgent('/api/agent/run/deterministic', 'agentDeterministicInput', false));
const externalAgentButton = document.getElementById('agentRunExternal');
if (externalAgentButton) externalAgentButton.addEventListener('click', () => runAgent('/api/agent/run/external', 'agentExternalInput', true));


async function loadCampaigns() {
  const rows = await api('/api/agent-campaigns?limit=50');
  const list = document.getElementById('campaignList');
  if (!list) return;
  list.innerHTML = rows.map(c => `<div class="item"><div><code>${esc(c.status)}</code><strong>${esc(c.name)}</strong><small>${esc(c.id)} · runs ${esc((c.counters || {}).runs ?? 0)}</small></div><div class="actions"><button data-campaign-detail="${esc(c.id)}">Detail</button></div></div>`).join('') || '<div class="empty">尚無 Campaign</div>';
  list.querySelectorAll('button[data-campaign-detail]').forEach(button => button.addEventListener('click', async () => {
    try {
      const detail = await api(`/api/agent-campaigns/${encodeURIComponent(button.dataset.campaignDetail)}`);
      const input = document.getElementById('campaignSelectedId');
      if (input) input.value = detail.id;
      document.getElementById('campaignDetail').textContent = JSON.stringify(detail, null, 2);
    } catch (e) { toast(e.message, true); }
  }));
}

async function aggregateCampaign() {
  const id = document.getElementById('campaignSelectedId').value.trim();
  if (!id) { toast('campaign id 必填', true); return; }
  try {
    const packets = await api(`/api/agent-campaigns/${encodeURIComponent(id)}/aggregate`, {method:'POST', body:{}});
    document.getElementById('campaignDetail').textContent = JSON.stringify({campaign_id:id, consensus_packets:packets}, null, 2);
    toast(`Consensus packets: ${packets.length}`);
    await loadCampaigns();
  } catch (e) { toast(e.message, true); }
}

const campaignCreateButton = document.getElementById('campaignCreate');
if (campaignCreateButton) campaignCreateButton.addEventListener('click', async () => {
  try {
    const campaign = await api('/api/agent-campaigns', {method:'POST', body:{name:document.getElementById('campaignName').value, task_text:document.getElementById('campaignTask').value, evaluator:'browser:campaign'}});
    document.getElementById('campaignSelectedId').value = campaign.id;
    document.getElementById('campaignDetail').textContent = JSON.stringify(campaign, null, 2);
    await loadCampaigns();
  } catch (e) { toast(e.message, true); }
});
const campaignAggregateButton = document.getElementById('campaignAggregate');
if (campaignAggregateButton) campaignAggregateButton.addEventListener('click', aggregateCampaign);

async function loadAutonomyStats() {
  const stats = await api('/api/autonomy/stats');
  const el = document.getElementById('autonomyStats');
  if (el) el.textContent = `decisions ${stats.decision_count} · commits ${stats.commit_count} · escalations ${stats.escalate_count} · rollbacks ${stats.rollback_count}`;
}

const autonomyForm = document.getElementById('autonomyExecuteForm');
if (autonomyForm) autonomyForm.addEventListener('submit', async event => {
  event.preventDefault();
  try {
    const action = JSON.parse(document.getElementById('autonomyAction').value);
    const packet = document.getElementById('autonomyConsensusPacket').value.trim();
    const body = {action, evaluator:'browser:autonomy'};
    if (packet) body.evidence = {consensus_packet_id: packet};
    const result = await api('/api/autonomy/execute', {method:'POST', body});
    document.getElementById('autonomyReceipt').textContent = JSON.stringify(result, null, 2);
    toast(result.commit ? 'Canonical commit completed' : `Decision: ${result.decision.decision}`);
    await Promise.all([loadAutonomyStats(), loadFields(), loadProposals(), loadStats()]);
  } catch (e) { toast(e.message, true); }
});

loadAutonomyStats().catch(() => {});
