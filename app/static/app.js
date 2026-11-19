const $ = (id) => document.getElementById(id);
let current = null;

async function api(path, opts = {}) {
  const r = await fetch(path, {headers: {"Content-Type": "application/json"}, ...opts});
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data));
  return data;
}
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const note = (el, text, ok) => { el.innerHTML = `<div class="msg ${ok ? "ok" : "err"}">${esc(text)}</div>`; };
const debounce = (fn, ms = 300) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

function tab(name) {
  for (const n of ["create", "edit"]) {
    $("p-" + n).classList.toggle("hidden", n !== name);
    $("t-" + n).classList.toggle("on", n === name);
  }
}
$("t-create").onclick = () => tab("create");
$("t-edit").onclick = () => tab("edit");

function fill(sel, items, def) {
  sel.innerHTML = items.map((i) => `<option value="${i.id}">${esc(i.name)}</option>`).join("");
  if (def && items.some((i) => i.id === def)) sel.value = def;
}

async function init() {
  const m = await api("/api/meta");
  fill($("c-domain"), m.domains, m.defaults.domain_id);
  fill($("c-group"), m.groups, m.defaults.group_id);
  fill($("c-source"), m.sources, m.defaults.source_id);
  $("c-name").value = m.defaults.prefix || "";
}

$("c-offer").oninput = debounce(async () => {
  const id = $("c-offer").value;
  $("c-offer-name").textContent = "";
  if (!id) return;
  const found = await api("/api/offers?q=" + encodeURIComponent(id)).catch(() => []);
  const hit = found.find((o) => String(o.id) === id);
  $("c-offer-name").textContent = hit ? hit.name : "Оффер не найден";
});

$("c-go").onclick = async () => {
  $("c-go").disabled = true;
  try {
    const c = await api("/api/campaigns", {method: "POST", body: JSON.stringify({
      name: $("c-name").value, geo: $("c-geo").value, offer_id: Number($("c-offer").value),
      domain_id: Number($("c-domain").value), group_id: Number($("c-group").value),
      source_id: Number($("c-source").value),
    })});
    note($("c-msg"), `Кампания создана: ${c.name} (ID ${c.id})`, true);
    $("c-msg").innerHTML += `<div class="hint"><a href="#" id="c-open">Открыть в редакторе</a></div>`;
    $("c-open").onclick = (e) => { e.preventDefault(); tab("edit"); openCampaign(c.id); };
  } catch (e) { note($("c-msg"), e.message, false); }
  $("c-go").disabled = false;
};

function suggestions(list, items, onPick) {
  list.classList.toggle("hidden", !items.length);
  list.innerHTML = items.map((i, n) => `<li data-n="${n}">${esc(i.label)}</li>`).join("");
  list.onclick = (e) => { const li = e.target.closest("li"); if (li) { list.classList.add("hidden"); onPick(items[li.dataset.n]); } };
}

let campPage = 1;
async function searchCampaigns(append = false) {
  const q = $("e-q").value.trim();
  if (!q) return suggestions($("e-list"), [], null);
  campPage = append ? campPage + 1 : 1;
  const r = await api(`/api/campaigns?q=${encodeURIComponent(q)}&page=${campPage}`).catch(() => ({items: [], has_more: false}));
  const prev = append ? [...$("e-list").querySelectorAll("li[data-n]")].map((li) => li._item) : [];
  const items = prev.concat(r.items.map((c) => ({id: c.id, label: `${c.name} (ID ${c.id})`})));
  suggestions($("e-list"), items, (i) => openCampaign(i.id));
  [...$("e-list").querySelectorAll("li[data-n]")].forEach((li, n) => { li._item = items[n]; });
  if (r.has_more) {
    $("e-list").insertAdjacentHTML("beforeend", `<li id="e-more" style="color:var(--acc)">Показать ещё</li>`);
    $("e-more").onclick = (e) => { e.stopPropagation(); searchCampaigns(true); };
  }
}
$("e-q").oninput = debounce(() => searchCampaigns(false));
$("e-int").onchange = () => current && openCampaign(current);

const num = (v, d = 2) => Number(v || 0).toLocaleString("ru-RU", {maximumFractionDigits: d});

async function openCampaign(id) {
  current = id;
  $("e-msg").innerHTML = "";
  try {
    const c = await api(`/api/campaigns/${id}?interval=${$("e-int").value}`);
    $("e-card").classList.remove("hidden");
    $("e-title").textContent = c.name;
    $("e-sub").textContent = `ID ${c.id} · ${c.domain || "без домена"} · группа ${c.group || "нет"}`;
    $("e-rows").innerHTML = c.offers.map((o) => `<tr>
      <td class="name">${esc(o.name)}<div class="hint">ID ${o.offer_id}</div></td>
      <td><input class="share" type="number" min="1" max="100" value="${o.share}" data-id="${o.offer_id}" data-old="${o.share}" style="width:64px;padding:5px 6px">%</td><td>${num(o.clicks, 0)}</td><td>${num(o.conversions, 0)}</td><td>${num(o.cr)}</td>
      <td>${num(o.revenue)}</td><td>${num(o.cost)}</td><td>${num(o.profit)}</td><td>${num(o.roi)}</td>
      <td><button class="btn del" data-id="${o.offer_id}">Удалить</button></td></tr>`).join("")
      || `<tr><td colspan="10" class="hint">В кампании нет офферов</td></tr>`;
    const t = c.totals;
    $("e-foot").innerHTML = `<tr><td>Итого</td><td></td><td>${num(t.clicks, 0)}</td><td>${num(t.conversions, 0)}</td><td></td>
      <td>${num(t.revenue)}</td><td>${num(t.cost)}</td><td>${num(t.profit)}</td><td></td><td></td></tr>`;
  } catch (e) { $("e-card").classList.remove("hidden"); note($("e-msg"), e.message, false); }
}

$("e-rows").onchange = async (e) => {
  const inp = e.target.closest("input.share");
  if (!inp) return;
  try {
    await api(`/api/campaigns/${current}/offers/${inp.dataset.id}`, {method: "PUT", body: JSON.stringify({share: Number(inp.value)})});
    await openCampaign(current);
    note($("e-msg"), "Доля сохранена, остальные пересчитаны", true);
  } catch (err) { inp.value = inp.dataset.old; note($("e-msg"), err.message, false); }
};

$("e-rows").onclick = async (e) => {
  const b = e.target.closest("button.del");
  if (!b || !confirm("Удалить оффер из кампании?")) return;
  try {
    await api(`/api/campaigns/${current}/offers/${b.dataset.id}`, {method: "DELETE"});
    await openCampaign(current);
    note($("e-msg"), "Оффер удалён", true);
  } catch (err) { note($("e-msg"), err.message, false); }
};

let pickedOffer = null;
$("a-q").oninput = debounce(async () => {
  pickedOffer = /^\d+$/.test($("a-q").value.trim()) ? Number($("a-q").value.trim()) : null;
  const q = $("a-q").value.trim();
  if (!q) return suggestions($("a-list"), [], null);
  const items = await api("/api/offers?q=" + encodeURIComponent(q)).catch(() => []);
  suggestions($("a-list"), items.map((o) => ({id: o.id, label: `${o.name} (ID ${o.id})`})),
    (i) => { pickedOffer = i.id; $("a-q").value = String(i.id); });
});
$("a-go").onclick = async () => {
  if (!pickedOffer) return note($("e-msg"), "Укажите ID оффера или выберите из списка", false);
  try {
    await api(`/api/campaigns/${current}/offers`, {method: "POST", body: JSON.stringify({offer_id: pickedOffer})});
    $("a-q").value = ""; pickedOffer = null;
    await openCampaign(current);
    note($("e-msg"), "Оффер добавлен", true);
  } catch (err) { note($("e-msg"), err.message, false); }
};

init().catch((e) => note($("c-msg"), e.message, false));
