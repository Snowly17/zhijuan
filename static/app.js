const $ = (s) => document.querySelector(s);
const T = window.I18N_APP || {};

// 纯粹的 key 映射，绝不留中文兜底
const _t = (key) => T[key] || key;

function setMsg(el, text, type) {
  el.innerHTML = text;
  el.className = "msg " + (type || "");
}

/* 从 "XXX-第N卷" 里提取 N */
function extractVolumeNumber(name) {
  // 注意：如果你的多语言环境下卷名格式完全变了，这里可能也需要适配
  const m = name.match(/(?:第|Vol\.?|Part)\s*(\d+)\s*(?:卷)?/i);
  return m ? parseInt(m[1], 10) : null;
}

function refreshSelection() {
  const checked = document.querySelectorAll(".paper-checkbox:checked");
  const countEl = $("#selCount");
  const btn = $("#btnDeleteSelected");
  if (countEl) countEl.textContent = checked.length;
  if (btn) btn.disabled = checked.length === 0;
}

function refreshRangePreview() {
  const preview = $("#rangePreview");
  if (!preview) return;

  const prefix = $("#rangePrefix").value.trim();
  const start = parseInt($("#rangeStart").value, 10) || 0;
  const end = parseInt($("#rangeEnd").value, 10) || 0;
  if (start <= 0 || end <= 0 || end < start) {
    preview.textContent = "";
    return;
  }

  let matched = 0;
  document.querySelectorAll(".paper-item").forEach(item => {
    const name = item.dataset.name;
    if (prefix && !name.startsWith(prefix)) return;
    const n = extractVolumeNumber(name);
    if (n === null) return;
    if (n >= start && n <= end) matched++;
  });

  // 这里如果是纯英文环境，也许你应该用变量替换，比如 _t('js.match_count').replace('{n}', matched)
  preview.textContent = matched ? _t('match_count').replace('{n}', matched) : _t('no_match_range');
  preview.className = "range-hint" + (matched ? " ok" : " warn");
}

async function deletePids(pids, label) {
  if (!pids.length) {
    alert(_t('no_match'));
    return;
  }
  const msg = _t('confirm_batch_del').replace('{n}', pids.length).replace('{label}', label);
  if (!confirm(msg)) return;

  const res = await fetch("/api/papers/delete_batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pids })
  });
  const data = await res.json();
  if (!data.ok) { alert(data.msg || _t('del_fail')); return; }
  location.reload();
}

document.addEventListener("DOMContentLoaded", () => {
  $("#uploadForm").onsubmit = async (e) => {
    e.preventDefault();
    const form = new FormData(e.target);
    const msg = $("#uploadMsg");
    setMsg(msg, _t('uploading'), "");

    const res = await fetch("/api/upload", { method: "POST", body: form });
    const data = await res.json();
    if (!data.ok) { setMsg(msg, "✗ " + (data.msg || _t('upload_fail')), "err"); return; }
    setMsg(msg, _t('upload_ok').replace('{n}', data.count), "ok");
    setTimeout(() => location.reload(), 800);
  };

  const genForm = $("#genForm");
  if (genForm) {
    genForm.onsubmit = async (e) => {
      e.preventDefault();
      const body = Object.fromEntries(new FormData(e.target).entries());
      const msg = $("#genMsg");
      setMsg(msg, _t('generating'), "");

      const res = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      const data = await res.json();
      if (!data.ok) { setMsg(msg, "✗ " + (data.msg || _t('gen_fail')), "err"); return; }
      setMsg(msg, _t('gen_ok').replace('{n}', data.count), "ok");
      setTimeout(() => location.reload(), 800);
    };
  }

  document.querySelectorAll(".paper-checkbox").forEach(cb => {
    cb.onchange = refreshSelection;
  });
  refreshSelection();

  const btnAll = $("#btnSelectAll");
  if (btnAll) btnAll.onclick = () => {
    document.querySelectorAll(".paper-checkbox").forEach(cb => cb.checked = true);
    refreshSelection();
  };

  const btnInv = $("#btnSelectInvert");
  if (btnInv) btnInv.onclick = () => {
    document.querySelectorAll(".paper-checkbox").forEach(cb => cb.checked = !cb.checked);
    refreshSelection();
  };

  const btnNone = $("#btnSelectNone");
  if (btnNone) btnNone.onclick = () => {
    document.querySelectorAll(".paper-checkbox").forEach(cb => cb.checked = false);
    refreshSelection();
  };

  const btnDelSelected = $("#btnDeleteSelected");
  if (btnDelSelected) {
    btnDelSelected.onclick = async () => {
      const pids = Array.from(document.querySelectorAll(".paper-checkbox:checked")).map(cb => cb.value);
      await deletePids(pids, _t('selected'));
    };
  }

  ["#rangePrefix", "#rangeStart", "#rangeEnd"].forEach(sel => {
    const el = $(sel);
    if (el) el.oninput = refreshRangePreview;
  });
  refreshRangePreview();

  const btnRange = $("#btnDeleteRange");
  if (btnRange) {
    btnRange.onclick = async () => {
      const prefix = $("#rangePrefix").value.trim();
      const start = parseInt($("#rangeStart").value, 10) || 0;
      const end = parseInt($("#rangeEnd").value, 10) || 0;

      if (start <= 0 || end <= 0) { alert(_t('invalid_range')); return; }
      if (end < start) { alert(_t('range_error')); return; }

      const pids = [];
      document.querySelectorAll(".paper-item").forEach(item => {
        const name = item.dataset.name;
        if (prefix && !name.startsWith(prefix)) return;
        const n = extractVolumeNumber(name);
        if (n === null) return;
        if (n >= start && n <= end) pids.push(item.dataset.pid);
      });

      const label = `${start} - ${end}`;
      await deletePids(pids, label);
    };
  }

  document.querySelectorAll(".btn-delete-paper").forEach(btn => {
    btn.onclick = async () => {
      const pid = btn.dataset.pid;
      const item = btn.closest(".paper-item");
      const name = item.querySelector(".paper-name").textContent.trim();

      const msg = _t('confirm_del_paper').replace('{name}', name);
      if (!confirm(msg)) return;

      const res = await fetch(`/api/paper/${pid}`, { method: "DELETE" });
      const data = await res.json();
      if (!data.ok) { alert(data.msg || _t('del_fail')); return; }
      item.remove();
      refreshSelection();
      refreshRangePreview();
    };
  });
});