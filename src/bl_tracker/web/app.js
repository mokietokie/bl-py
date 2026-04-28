const $ = (q) => document.querySelector(q);
const tbody = $("#t tbody");
const progress = $("#progress");

async function load() {
  const r = await fetch("/shipments");
  const rows = await r.json();
  tbody.innerHTML = "";
  for (const s of rows) tbody.appendChild(rowEl(s));
}

function rowEl(s = {}) {
  const tr = document.createElement("tr");
  if (s.eta_changed) tr.classList.add("changed");
  if (s.id != null) tr.dataset.id = s.id;
  tr.innerHTML = `
    <td><input type="checkbox" class="sel"></td>
    <td contenteditable data-f="bl_no">${s.bl_no ?? ""}</td>
    <td contenteditable data-f="imo_no">${s.imo_no ?? ""}</td>
    <td>${s.eta ?? ""}</td>
    <td>${s.eta_prev_kst ?? ""}</td>
    <td>${s.location ?? ""}</td>
    <td>${s.lat != null ? s.lat.toFixed(4) + ", " + s.lon.toFixed(4) : ""}</td>
    <td>${s.bl_refreshed_at ?? ""}</td>
    <td>${s.loc_refreshed_at ?? ""}</td>
    <td contenteditable data-f="memo">${s.memo ?? ""}</td>
    <td>
      <button class="bl">BL새로고침</button>
      <button class="loc">위치새로고침</button>
      <button class="del">삭제</button>
    </td>`;

  const syncButtons = () => {
    const saved = !!tr.dataset.id;
    tr.querySelector(".bl").disabled = !saved;
    tr.querySelector(".loc").disabled = !saved;
  };
  syncButtons();

  tr.querySelector(".bl").onclick = () => tr.dataset.id && single(Number(tr.dataset.id), "bl");
  tr.querySelector(".loc").onclick = () => tr.dataset.id && single(Number(tr.dataset.id), "loc");
  tr.querySelector(".del").onclick = async () => {
    if (!tr.dataset.id) { tr.remove(); return; }
    await fetch(`/shipments/${tr.dataset.id}`, { method: "DELETE" });
    load();
  };

  tr.querySelectorAll("[contenteditable]").forEach(el => {
    el.addEventListener("blur", async () => {
      const val = el.textContent.trim();
      if (tr.dataset.id) {
        await fetch(`/shipments/${tr.dataset.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ [el.dataset.f]: val }),
        });
        return;
      }
      const bl = tr.querySelector('[data-f="bl_no"]').textContent.trim();
      if (!bl) return;
      const imo = tr.querySelector('[data-f="imo_no"]').textContent.trim() || null;
      const memo = tr.querySelector('[data-f="memo"]').textContent.trim() || null;
      const r = await fetch("/shipments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bl_no: bl, imo_no: imo, memo }),
      });
      if (r.status === 409) { progress.textContent = `중복 BL: ${bl}`; return; }
      if (!r.ok)            { progress.textContent = `생성 실패: ${r.status}`; return; }
      const created = await r.json();
      tr.dataset.id = created.id;
      syncButtons();
      progress.textContent = `${bl} 추가됨`;
    });
  });
  return tr;
}

async function single(id, target) {
  progress.textContent = `${id} ${target} 갱신중…`;
  const r = await fetch(`/shipments/${id}/refresh-${target}`, { method: "POST" });
  const j = await r.json();
  progress.textContent = `${id} ${target}: ${j.status}`;
  load();
}

function selectedIds() {
  return [...tbody.querySelectorAll("tr")]
    .filter(tr => tr.querySelector(".sel").checked && tr.dataset.id)
    .map(tr => Number(tr.dataset.id));
}

async function bulk(ids) {
  if (!ids.length) { progress.textContent = "선택 없음"; return; }
  progress.textContent = `0/${ids.length * 2}`;
  const resp = await fetch("/shipments/refresh-bulk", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids, targets: ["bl", "loc"] }),
  });
  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value);
    const lines = buf.split("\n");
    buf = lines.pop();
    for (const line of lines) {
      if (line.startsWith("data:")) {
        try {
          const ev = JSON.parse(line.slice(5).trim());
          progress.textContent = `${ev.done}/${ev.total}`;
        } catch {}
      }
    }
  }
  load();
  progress.textContent += " 완료";
}

$("#btn-refresh-selected").onclick = () => bulk(selectedIds());
$("#btn-refresh-all").onclick = () => {
  const ids = [...tbody.querySelectorAll("tr")]
    .filter(tr => tr.dataset.id)
    .map(tr => Number(tr.dataset.id));
  bulk(ids);
};
$("#chk-all").onchange = (e) => {
  tbody.querySelectorAll(".sel").forEach(c => c.checked = e.target.checked);
};
$("#btn-add").onclick = () => {
  const tr = rowEl();
  tbody.appendChild(tr);
  tr.querySelector('[data-f="bl_no"]').focus();
};
$("#btn-import").onclick = () => $("#file-import").click();
$("#file-import").onchange = async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f);
  const r = await fetch("/import/excel", { method: "POST", body: fd });
  const j = await r.json();
  progress.textContent = `${j.imported}건 import`;
  load();
};
$("#btn-export").onclick = () => { window.location = "/export/excel"; };

load();
