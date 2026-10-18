/* Keyboard-driven batch sign-off UI (A/R/E, J/K).
   Every approve POSTs to sign_off via /review/{madhhab}/{id}/approve - the only
   path that flips verified:true. Unsigned items stay labelled غير موثّق and are
   only handled as matn (copy-as-fatwa is never offered). */
(function () {
  "use strict";

  var csrfMeta = document.querySelector('meta[name="csrf"]');
  var csrf = csrfMeta ? csrfMeta.content : "";
  var state = { items: [], idx: 0, progress: null, signed: 0, pending: 0, loaded: false };

  function el(id) { return document.getElementById(id); }
  function setv(id, v) { var e = el(id); if (e) e.value = v == null ? "" : String(v); }

  function fmtMinutes(seconds) {
    if (!isFinite(seconds) || seconds <= 0) return "غير متاح";
    var m = Math.round(seconds / 60);
    if (m < 60) return m + " دقيقة";
    var h = Math.floor(m / 60), r = m % 60;
    return h + " ساعة" + (r ? " و" + r + " دقيقة" : "");
  }

  function toast(msg, kind) {
    var t = el("toast");
    t.textContent = msg;
    t.className = kind || "";
  }

  function updateProgress() {
    var p = state.progress;
    if (!p) return;
    var total = p.total || 1;
    var pct = (100 * state.signed) / total;
    el("bar").value = pct;
    el("progress-text").textContent =
      "موثّق: " + state.signed + " / " + p.total + " (" + pct.toFixed(1) + "%) — المتبقي: " + state.pending;
    el("eta").textContent = "الوقت المتوقع المتبقي: " + fmtMinutes(state.pending * p.seconds_per_page);
  }

  function addMeta(term, value) {
    if (value == null || value === "") return;
    var dl = el("source-meta");
    var dt = document.createElement("dt");
    dt.textContent = term;
    var dd = document.createElement("dd");
    dd.textContent = String(value);
    dl.appendChild(dt);
    dl.appendChild(dd);
  }

  function current() {
    if (!state.items.length) return null;
    return state.items[Math.max(0, Math.min(state.idx, state.items.length - 1))];
  }

  function itemPageLabel(it) {
    if (it.page != null) return String(it.page);
    if (it.page_hint != null) return it.page_hint + " (ترقيم مبدئي من الرقمنة - أكّدها من الطبعة)";
    return "غير محددة (أدخلها من الطبعة المطبوعة)";
  }

  function render() {
    var empty = el("empty"), bench = el("workbench");
    if (!state.items.length) {
      bench.hidden = true;
      empty.hidden = false;
      return;
    }
    bench.hidden = false;
    empty.hidden = true;
    if (state.idx >= state.items.length) state.idx = state.items.length - 1;
    if (state.idx < 0) state.idx = 0;
    var it = state.items[state.idx];

    var pendingTotal = state.progress ? state.progress.pending : state.items.length;
    el("position").textContent = "العنصر " + (state.idx + 1) + " من " + state.items.length +
      " (المعروض الآن؛ المتبقي كله: " + pendingTotal + ")" +
      " - طُلب " + (it.direct_hits || 0) + " مرة في أسئلة المستخدمين";
    el("text").value = it.text || "";
    setv("work", it.work);
    setv("author", it.author);
    setv("edition", it.edition);
    setv("volume", it.page != null ? (it.volume || 1) : (it.page_hint != null ? 1 : ""));
    setv("page", it.page != null ? it.page : (it.page_hint != null ? it.page_hint : ""));
    setv("provenance", it.provenance);
    setv("license", it.license);
    setv("note", "");

    var badge = el("status-badge");
    badge.textContent = it.verified ? "موثّق" : "غير موثّق - يحتاج مراجعة شيخ";
    badge.style.background = it.verified ? "#1b5e20" : "#b3261e";

    var dl = el("source-meta");
    dl.textContent = "";
    addMeta("الكتاب", it.work);
    addMeta("المؤلف", it.author);
    addMeta("الطبعة", it.edition);
    addMeta("الصفحة", itemPageLabel(it));
    addMeta("المذهب", it.madhhab);
    addMeta("الترخيص", it.license);
    addMeta("مسائل فتوى رجعت هذه الصفحة (تحليلات الملفات)", String(it.direct_hits || 0));
    addMeta("سجل الرقمنة", it.provenance);

    var box = el("scan-links");
    box.textContent = "";
    var links = it.scan_links || [];
    if (!links.length) {
      var p = document.createElement("p");
      p.className = "hint";
      p.textContent = "لا يوجد رابط مسح موثّق لهذا المصدر — قارن مع سجل الرقمنة أعلاه.";
      box.appendChild(p);
    }
    links.forEach(function (l) {
      var a = document.createElement("a");
      a.href = l.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = l.label;
      box.appendChild(a);
      box.appendChild(document.createElement("br"));
    });

    el("reject-bar").hidden = true;
    el("reject-reason").value = "";
  }

  function post(url, fd) {
    fd.append("csrf", csrf);
    return fetch(url, {
      method: "POST",
      body: fd,
      headers: { "X-CSRF-Token": csrf, "Accept": "application/json" }
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) throw new Error(j.detail || ("HTTP " + r.status));
        return j;
      });
    });
  }

  function formData(includeNote) {
    var fd = new FormData();
    ["work", "author", "edition", "volume", "page", "provenance", "license"].forEach(function (k) {
      var e = el(k);
      if (e) fd.append(k, e.value);
    });
    fd.append("text", el("text").value);
    if (includeNote) fd.append("note", el("note").value);
    return fd;
  }

  function itemUrl(suffix) {
    var it = current();
    return "/review/" + it.madhhab + "/" + encodeURIComponent(it.id) + "/" + suffix;
  }

  function approve() {
    var it = current();
    if (!it) return;
    post(itemUrl("approve"), formData(true))
      .then(function (res) {
        toast("تم التوقيع — " + (res.label || "موثّق") + " بواسطة " + (res.verified_by || ""), "ok");
        state.items.splice(state.idx, 1);
        state.signed += 1;
        state.pending -= 1;
        state.progress.signed = state.signed;
        state.progress.pending = state.pending;
        updateProgress();
        render();
      })
      .catch(function (e) { toast("تعذّر التوثيق: " + e.message, "err"); });
  }

  function showReject() {
    if (!current()) return;
    el("reject-bar").hidden = false;
    el("reject-reason").focus();
  }

  function hideReject() {
    el("reject-bar").hidden = true;
    el("reject-reason").value = "";
  }

  function confirmReject() {
    var it = current();
    if (!it) return;
    var reason = el("reject-reason").value.trim();
    if (!reason) { toast("سبب الرفض إلزامي", "err"); return; }
    var fd = new FormData();
    fd.append("reason", reason);
    post(itemUrl("reject"), fd)
      .then(function () {
        toast("سُجّل الرفض — النص باقٍ منقولاً من الكتب بلا توقيع", "ok");
        state.items.splice(state.idx, 1);
        state.pending -= 1;
        state.progress.pending = state.pending;
        hideReject();
        updateProgress();
        render();
      })
      .catch(function (e) { toast("تعذّر الرفض: " + e.message, "err"); });
  }

  function fixEdition() {
    var it = current();
    if (!it) return;
    post(itemUrl("fix-edition"), formData(true))
      .then(function () { toast("حُفظت تصحيحات الطبعة/النص — ما زال غير موثّق حتى التوقيع", "ok"); })
      .catch(function (e) { toast("تعذّر الحفظ: " + e.message, "err"); });
  }

  function copyMatn() {
    var it = current();
    if (!it) return;
    var page = it.page != null ? "ص" + it.page : (it.page_hint != null ? "ص" + it.page_hint + " (ترقيم مبدئي)" : "صفحة غير محددة");
    var src = "[" + (it.work || "كتاب") + "][" + (el("edition").value || it.edition || "طبعة") + "][" + page + "]";
    var out = el("text").value + "\n\n" + src + "\n" +
      "غير موثّق - يحتاج مراجعة شيخ - لا يُنسخ كفتوى (متن فقط)";
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(out).then(function () {
        toast("نُسخ المتن مع المصدر والتنبيه", "ok");
      }).catch(function () { toast("تعذّر النسخ", "err"); });
    } else {
      toast("النسخ غير متاح في هذا المتصفح", "err");
    }
  }

  function step(delta) {
    if (!state.items.length) return;
    state.idx = Math.max(0, Math.min(state.items.length - 1, state.idx + delta));
    render();
  }

  function focusEdition() {
    if (!current()) return;
    el("edition").focus();
    el("edition").select();
  }

  document.addEventListener("keydown", function (e) {
    var tag = (e.target.tagName || "").toLowerCase();
    var typing = tag === "input" || tag === "textarea" || tag === "select";
    if (typing) {
      if (e.key === "Escape") {
        e.target.blur();
        if (e.target.id === "reject-reason") hideReject();
      }
      if (e.key === "Enter" && e.target.id === "reject-reason") {
        e.preventDefault();
        confirmReject();
      }
      return;
    }
    var actions = {
      KeyJ: function () { step(1); },
      KeyK: function () { step(-1); },
      KeyA: approve,
      KeyR: showReject,
      KeyE: focusEdition,
      ArrowDown: function () { step(1); },
      ArrowUp: function () { step(-1); }
    };
    var fn = actions[e.code] || (e.code === undefined ? actions[e.key] : null);
    if (fn) {
      e.preventDefault();
      fn();
    }
  });

  el("btn-approve").addEventListener("click", approve);
  el("btn-reject").addEventListener("click", showReject);
  el("reject-confirm").addEventListener("click", confirmReject);
  el("reject-cancel").addEventListener("click", hideReject);
  el("btn-fix").addEventListener("click", fixEdition);
  el("btn-copy").addEventListener("click", copyMatn);
  el("btn-next").addEventListener("click", function () { step(1); });
  el("btn-prev").addEventListener("click", function () { step(-1); });

  fetch("/review/queue.json", { headers: { "Accept": "application/json" } })
    .then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(function (data) {
      state.items = data.items || [];
      state.progress = data.progress || null;
      state.signed = state.progress ? state.progress.signed : 0;
      state.pending = state.progress ? state.progress.pending : state.items.length;
      el("reviewer").textContent = data.user || "";
      state.loaded = true;
      updateProgress();
      render();
      if (state.items.length) {
        toast("جاهز — البدء بأهم صفحة مطلوبة (A توثيق / R رفض / E تصحيح)", "ok");
      }
    })
    .catch(function (e) {
      el("progress-text").textContent = "تعذّر تحميل قائمة التوثيق: " + e.message;
    });
})();
