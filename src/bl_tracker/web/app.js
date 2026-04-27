const $ = (q) => document.querySelector(q);
const tbody = $("#t tbody");
const progress = $("#progress");

async function load() {
  const r = await fetch("/shipments");
  const rows = await r.json();
  tbody.innerHTML = "";
  for (const s of rows) tbody.appendChild(rowEl(s));
}

function rowEl(s) {
  const tr = document.createElement("tr");
  if (s.eta_changed) tr.classList.add("changed");
  tr.dataset.id = s.id;
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
  tr.querySelector(".bl").onclick = () => single(s.id, "bl");
  tr.querySelector(".loc").onclick = () => single(s.id, "loc");
  tr.querySelector(".del").onclick = async () => {
    await fetch(`/shipments/${s.id}`, { method: "DELETE" });
    load();
  };
  tr.querySelectorAll("[contenteditable]").forEach(el => {
    el.addEventListener("blur", async () => {
      const body = { [el.dataset.f]: el.textContent.trim() };
      await fetch(`/shipments/${s.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
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
    .filter(tr => tr.querySelector(".sel").checked)
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
  const ids = [...tbody.querySelectorAll("tr")].map(tr => Number(tr.dataset.id));
  bulk(ids);
};
$("#chk-all").onchange = (e) => {
  tbody.querySelectorAll(".sel").forEach(c => c.checked = e.target.checked);
};
$("#btn-add").onclick = async () => {
  const bl = prompt("BL 번호");
  if (!bl) return;
  const imo = prompt("IMO 번호 (선택)") || null;
  const r = await fetch("/shipments", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bl_no: bl, imo_no: imo }),
  });
  if (r.status === 409) alert("중복된 BL");
  load();
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
