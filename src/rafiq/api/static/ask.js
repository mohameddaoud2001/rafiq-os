(function () {
  "use strict";

  var lastQuery = "";

  var MADHHAB_NAMES = {
    maliki: "المذهب المالكي",
    hanafi: "المذهب الحفي",
    shafii: "المذهب الشافعي",
    hanbali: "المذهب الحنبلي"
  };

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function sourceLink(url, label) {
    if (!url) return null;
    var a = el("a", null, label || url);
    a.href = url;
    a.rel = "noopener";
    a.target = "_blank";
    return a;
  }

  function findingCard(f) {
    var card = el("div", "finding");
    card.appendChild(el("span", f.verified ? "badge badge-signed" : "badge badge-unsigned",
      f.label || (f.verified ? "موثّق" : "منقول من الكتب")));
    if (f.source_label) card.appendChild(el("div", "source-line", f.source_label));
    if (f.page_hint) {
      card.appendChild(el("div", "page-hint",
        "الصفحة في النسخة المرقمنة: " + f.page_hint + " (للمطابقة)"));
    }
    card.appendChild(el("pre", "matn", f.excerpt || ""));
    var links = el("div", "links");
    var scan = sourceLink(f.scan_url, "ملف الرقمنة");
    if (scan) links.appendChild(scan);
    var raw = el("span", "empty-note", f.provenance || "");
    links.appendChild(raw);
    card.appendChild(links);
    return card;
  }

  function renderCitations(container, citations) {
    (citations || []).forEach(function (cit) {
      var findings = cit.findings || [];
      if (!findings.length) return;
      var mh = (cit.extra && cit.extra.madhhab) || findings[0].madhhab || "";
      var head = el("h2", "work-title",
        (MADHHAB_NAMES[mh] || mh) + " - " + (findings[0].work || ""));
      if (cit.extra && cit.extra.comparison) head.textContent += " (مقارنة)";
      container.appendChild(head);
      findings.forEach(function (f) {
        container.appendChild(findingCard(f));
      });
    });
  }

  function shareRow(container, query) {
    var url = window.location.origin + "/";
    var text = query
      ? "سؤال: " + query + "\nجواب منقول من كتب معتمدة مذكورة (منقول من الكتب - بلا توقيع مفتٍ، وليس فتوى مفتٍ)"
      : "الرفيق المسند - جواب من الكتب مع مصادره";
    var enc = encodeURIComponent;
    var targets = [
      ["واتساب", "https://wa.me/?text=" + enc(text + "\n" + url)],
      ["تليجرام", "https://t.me/share/url?url=" + enc(url) + "&text=" + enc(text)],
      ["إكس", "https://twitter.com/intent/tweet?text=" + enc(text) + "&url=" + enc(url)]
    ];
    var wrap = el("div", "share");
    wrap.appendChild(el("div", "source-line", "انشره ليعمّ النفع:"));
    var row = el("div", "links");
    targets.forEach(function (t) {
      var a = el("a", null, "شارك على " + t[0]);
      a.href = t[1];
      a.target = "_blank";
      a.rel = "noopener";
      row.appendChild(a);
    });
    wrap.appendChild(row);
    container.appendChild(wrap);
  }

  function renderFatwa(container, fatwa) {
    clear(container);
    if (!fatwa || !fatwa.text) return;
    container.appendChild(el("h2", "work-title", "الجواب من الكتب"));
    container.appendChild(el("pre", "matn", fatwa.text));
    if (fatwa.based_on && fatwa.based_on.length) {
      container.appendChild(el("div", "source-line", "أسانيد الجواب: " + fatwa.based_on.join(" ، ")));
    }
  }

  function render(data) {
    var status = document.getElementById("status");
    var bannerBox = document.getElementById("banner-box");
    var fatwa = document.getElementById("fatwa");
    var message = document.getElementById("message");
    var citations = document.getElementById("citations");
    clear(status); clear(bannerBox); clear(fatwa); clear(message); clear(citations);
    status.textContent = "";

    if (data.blocked) {
      message.textContent = data.reason || "تعذر معالجة السؤال.";
      return;
    }

    (data.banners || []).forEach(function (b) {
      bannerBox.appendChild(el("div", null, b));
    });

    renderFatwa(fatwa, data.fatwa);

    if (data.message) {
      message.textContent = data.message;
    }

    var any = false;
    renderCitations(citations, data.citations);
    if (citations.childNodes.length) any = true;

    if (!any && (!data.informational || !data.informational.length)) {
      citations.appendChild(el("p", "empty-note",
        "لم يُعرض نص مطابق. سُجّلت المسألة في سجل الفجوات للبحث عن نص لها."));
    }

    if (lastQuery) shareRow(citations, lastQuery);

    if (data.dossier && data.dossier.id) {
      status.textContent = "سُجّلت المسألة في السجل (رقم " + data.dossier.id +
        "، الحالة " + (data.dossier.status || "PENDING") + ").";
    }
  }

  var form = document.getElementById("ask-form");
  if (!form) return;
  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var q = document.getElementById("q").value.trim();
    if (!q) return;
    lastQuery = q;
    var status = document.getElementById("status");
    status.textContent = "جارٍ البحث في المصادر...";
    fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: q, madhhab: document.getElementById("madhhab").value })
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        status.textContent = "";
        render(data);
      })
      .catch(function () {
        status.textContent = "";
        document.getElementById("message").textContent = "تعذر الاتصال بالخادم، حاول مرة أخرى.";
      });
  });
})();
