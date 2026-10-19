const PAPER_ID = window.PAPER_ID;
const T = window.I18N_EXAM || {};
const _t = (key) => T[key] || key;

function typeLabel(t) {
  return {
    single: _t('type_single'),
    multiple: _t('type_multiple'),
    judge: _t('type_judge'),
    blank: _t('type_blank'),
    short: _t('type_short')
  }[t] || t;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;",
    '"': "&quot;", "'": "&#39;"
  }[c]));
}

function renderQuestion(q, idx) {
  const div = document.createElement("div");
  div.className = "question";
  div.dataset.qid = q.id;
  div.dataset.type = q.type;

  let body = "";
  if (q.type === "single") {
    body = q.options.map((opt, i) => {
      const L = String.fromCharCode(65 + i);
      return `<label class="opt">
        <input type="radio" name="q_${q.id}" value="${L}">
        <span>${L}. ${escapeHtml(opt)}</span>
      </label>`;
    }).join("");
  } else if (q.type === "multiple") {
    body = q.options.map((opt, i) => {
      const L = String.fromCharCode(65 + i);
      return `<label class="opt">
        <input type="checkbox" name="q_${q.id}" value="${L}">
        <span>${L}. ${escapeHtml(opt)}</span>
      </label>`;
    }).join("");
  } else if (q.type === "judge") {
    body = `
      <label class="opt"><input type="radio" name="q_${q.id}" value="T"><span>${_t('judge_t')}</span></label>
      <label class="opt"><input type="radio" name="q_${q.id}" value="F"><span>${_t('judge_f')}</span></label>`;
  } else if (q.type === "blank") {
    body = `<input type="text" class="text-input" name="q_${q.id}" placeholder="${_t('ph_blank')}">`;
  } else if (q.type === "short") {
    body = `<textarea class="text-input" name="q_${q.id}" rows="3" placeholder="${_t('ph_blank')}"></textarea>`;
  }

  div.innerHTML = `
    <div class="q-head">
      <span class="q-index">${idx + 1}</span>
      <span class="q-type-tag">${q.type_label || typeLabel(q.type)}</span>
      <span class="q-score">${q.score} ${_t('points')}</span>
    </div>
    <div class="q-body">${escapeHtml(q.question)}</div>
    <div class="q-options">${body}</div>`;
  return div;
}

function collectAnswers() {
  const answers = {};
  document.querySelectorAll(".question").forEach(div => {
    const qid = div.dataset.qid;
    const type = div.dataset.type;
    if (type === "single" || type === "judge") {
      const sel = div.querySelector(`input[name="q_${qid}"]:checked`);
      answers[qid] = sel ? sel.value : "";
    } else if (type === "multiple") {
      const sels = div.querySelectorAll(`input[name="q_${qid}"]:checked`);
      answers[qid] = Array.from(sels).map(s => s.value);
    } else {
      const inp = div.querySelector(`[name="q_${qid}"]`);
      answers[qid] = inp ? inp.value : "";
    }
  });
  return answers;
}

document.addEventListener("DOMContentLoaded", async () => {
  const res = await fetch(`/api/paper/${PAPER_ID}`);
  const data = await res.json();
  if (!data.ok) {
    alert(data.msg || _t('load_fail'));
    return;
  }

  const list = document.getElementById("questionList");
  data.questions.forEach((q, i) => list.appendChild(renderQuestion(q, i)));

  document.getElementById("examForm").onsubmit = async (e) => {
    e.preventDefault();
    if (!confirm(_t('confirm_submit'))) return;

    const res2 = await fetch(`/api/submit/${PAPER_ID}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answers: collectAnswers() })
    });
    const r = await res2.json();
    if (!r.ok) {
      alert(r.msg || _t('submit_fail'));
      return;
    }
    window.location.href = `/paper/${PAPER_ID}/result/${r.result_id}`;
  };
});