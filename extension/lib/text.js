// Small text helpers shared by the classifier, memory and exports. No chrome.* here, so Node can test it.

const STOP = new Set(`a an the and or but of for to in on at by with from into onto about over under as is are was were be been
being am do does did doing have has had i me my we our you your it its this that these those what which who whom how why when where
there here then than so if not no yes just very can could should would will shall may might must get got make made new vs via using use
work working task tasks finish finishing do doing some any all more most up down out off again today tonight now thing things stuff
www com org net io html htm php asp index watch amp utm https http video youtube official channel page home online
free best top blog`.split(/\s+/));

// Tiny suffix stemmer: good enough to match "hackathons" to "hackathon" and "training" to "train".
export function stem(w) {
  if (w.length > 5 && w.endsWith("ing")) return w.slice(0, -3);
  if (w.length > 4 && w.endsWith("ies")) return w.slice(0, -3) + "y";
  if (w.length > 4 && w.endsWith("es") && /(sh|ch|x|ss)es$/.test(w)) return w.slice(0, -2);
  if (w.length > 3 && w.endsWith("s") && !w.endsWith("ss")) return w.slice(0, -1);
  if (w.length > 5 && w.endsWith("ed")) return w.slice(0, -2);
  return w;
}

export function words(text) {
  return (text || "").toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "").match(/[a-z0-9][a-z0-9+#]*/g) || [];
}

// Content words, stemmed, deduplicated.
export function keywords(text) {
  const out = new Set();
  for (const w of words(text)) {
    const s = stem(w);
    if (w.length < 2 || STOP.has(w) || STOP.has(s) || /^\d+$/.test(w)) continue;
    out.add(s);
  }
  return out;
}

export function domainOf(url) {
  try {
    const h = new URL(url).hostname.toLowerCase();
    return h.startsWith("www.") ? h.slice(4) : h;
  } catch {
    return "";
  }
}

export function matchesDomain(domain, list) {
  return list.some((d) => domain === d || domain.endsWith("." + d));
}

// One key per "page": drops the hash, and for search/video sites keeps only the parameter that names the page.
export function canonicalUrl(url) {
  try {
    const u = new URL(url);
    u.hash = "";
    const d = domainOf(url);
    const keep = (k) => {
      const v = u.searchParams.get(k);
      u.search = v ? `?${k}=${encodeURIComponent(v)}` : "";
    };
    if (d.endsWith("youtube.com") && u.pathname === "/watch") keep("v");
    else if (d.endsWith("youtube.com") && u.pathname === "/results") keep("search_query");
    else if (/(^|\.)(google|bing|duckduckgo)\.[a-z.]+$/.test(d) && u.pathname.startsWith("/search")) keep("q");
    else if (d === "duckduckgo.com") keep("q");
    else for (const k of [...u.searchParams.keys()]) if (/^(utm_|fbclid|gclid|ref$|si$)/.test(k)) u.searchParams.delete(k);
    return u.toString();
  } catch {
    return url;
  }
}

// The text the user typed into a search box, if this URL is a search results page.
export function searchQuery(url) {
  try {
    const u = new URL(url);
    return u.searchParams.get("q") || u.searchParams.get("search_query") || u.searchParams.get("query") || "";
  } catch {
    return "";
  }
}

// Words hidden in the URL path ("/watch/how-to-train-a-lora" -> "how to train a lora").
export function pathWords(url) {
  try {
    const u = new URL(url);
    return decodeURIComponent(u.pathname).replace(/[\/_\-.+]+/g, " ").trim();
  } catch {
    return "";
  }
}

export function jaccard(a, b) {
  if (!a.size && !b.size) return 1;
  let inter = 0;
  for (const x of a) if (b.has(x)) inter++;
  return inter / (a.size + b.size - inter || 1);
}

// How much two stated tasks mean the same thing (1 = identical keywords).
export function taskSimilarity(a, b) {
  return jaccard(keywords(a), keywords(b));
}
