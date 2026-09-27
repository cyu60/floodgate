// Offline classifier: a transparent baseline that works with no server, and the fallback when the model is offline.
// It scores P(distraction) relative to the stated task, so the same site can be on task or off task.
import { DISTRACTION_DOMAINS, REFERENCE_DOMAINS, SEARCH_DOMAINS, SOCIAL_DOMAINS, WORK_DOMAINS } from "./config.js";
import { domainOf, keywords, matchesDomain, pathWords, searchQuery } from "./text.js";

const FUN = /\b(funny|memes?|pranks?|compilation|gameplay|let'?s play|trailers?|reacts?|reaction|vlogs?|shorts|highlights|tiktoks?|challenge|asmr|mukbang|celebrity|gossip|drama|unboxing|try not to laugh|fails|satisfying|full movie|full episode|episode \d+|season \d+|music video|official video|lyrics|live ?stream|anime|manga|chapter \d+|nba|nfl|premier league|speedrun|tier list|roast|skit|viral|trending|kittens?|puppy|puppies|gta|minecraft|fortnite)\b/gi;
const LEARN = /\b(tutorial|how to|course|lecture|explained|explainer|introduction|intro to|guide|documentation|docs|reference|api|paper|talk|conference|keynote|workshop|lesson|learn|crash course|deep dive|walkthrough|in \d+ (seconds|minutes)|overview|primer|handbook|cheat ?sheet)\b/gi;
const CREATOR = /\b(content creator|creator|influencer|youtuber|tiktoker|streamer|social media|ugc|meme page)\b/i;

// Task words that say little on their own ("research", "project") count half.
const WEAK = new Set(["research", "model", "project", "learn", "study", "demo", "build", "app", "code", "write", "read", "plan", "review", "report", "prep", "idea", "design", "test"]);

const uniq = (m) => [...new Set((m || []).map((x) => x.toLowerCase()))];

function relevance(taskKw, pageKw) {
  if (!taskKw.size) return { score: 0, matched: [] };
  const matched = [];
  let credit = 0;
  for (const k of taskKw) {
    const hit = pageKw.has(k) || (k.length >= 5 && [...pageKw].some((p) => p.length >= 5 && (p.startsWith(k) || k.startsWith(p))));
    if (hit) {
      matched.push(k);
      credit += WEAK.has(k) ? 0.5 : 1;
    }
  }
  return { score: Math.min(1, credit / Math.min(2, taskKw.size)), matched };
}

/**
 * @param {{url:string,title?:string,description?:string,channel?:string,keywords?:string,siteName?:string,query?:string}} page
 * @param {{task?:string, profile?:string, mode?:string}} ctx
 * @returns {{p:number, reason:string, signals:object}}
 */
export function heuristicScore(page, ctx = {}) {
  const url = page.url || "";
  const domain = page.domain || domainOf(url);
  const query = page.query || searchQuery(url);
  const cueText = [page.title, page.description, page.channel, query].filter(Boolean).join(" ");
  const pageKw = keywords([page.title, page.description, page.channel, page.keywords, page.siteName, query, pathWords(url)].join(" "));
  const taskKw = keywords(ctx.task);
  const creator = ctx.mode === "creator" || CREATOR.test(ctx.profile || "");
  const social = matchesDomain(domain, SOCIAL_DOMAINS);
  const why = [];

  let kind, p;
  if (matchesDomain(domain, SEARCH_DOMAINS) && query) [kind, p] = ["search", 0.4];
  else if (matchesDomain(domain, WORK_DOMAINS)) [kind, p] = ["work", 0.2];
  else if (matchesDomain(domain, DISTRACTION_DOMAINS)) [kind, p] = ["distraction", 0.72];
  else if (matchesDomain(domain, REFERENCE_DOMAINS)) [kind, p] = ["reference", 0.45];
  else [kind, p] = ["unknown", 0.45];

  const fun = uniq(cueText.match(FUN));
  const learn = uniq(cueText.match(LEARN));
  const task = relevance(taskKw, pageKw);
  // Your own "about me" can make a page relevant too (half weight): a musician's music videos, a chef's recipes.
  const about = relevance(keywords(ctx.profile), pageKw);
  const rel = Math.max(task.score, about.score * 0.5);

  if (rel > 0) {
    p -= 0.55 * rel + (learn.length ? 0.1 * rel : 0);
    why.push(task.score ? `About your task (${task.matched.map((m) => `“${m}”`).join(", ")})` : "Matches what you told Floodgate about yourself");
  } else if (taskKw.size) {
    p += 0.15;
    if (ctx.mode === "research" && learn.length) {
      p -= 0.2;
      why.push("Learning material, but not about your task");
    } else if (learn.length) why.push("Informative, but not about your task");
    else if (!fun.length) why.push("Not about your task");
  } else why.push("No task set");

  if (creator && social) {
    p -= 0.3 + Math.min(0.2, 0.1 * fun.length);
    why.push("Creator mode: trends count as work");
  } else if (fun.length) {
    p += Math.min(0.25, 0.12 * fun.length) * (1 - rel);
    why.push(`Entertainment cues (${fun.slice(0, 2).map((f) => `“${f}”`).join(", ")})`);
  }
  if (kind === "work" && rel === 0) why.push("Work tool");
  if (kind === "distraction" && rel === 0 && !(creator && social)) why.push("Usually a distraction site");

  p = Math.min(0.98, Math.max(0.02, p));
  return {
    p: Math.round(p * 1000) / 1000,
    reason: why.join(" · "),
    signals: { domain, kind, relevance: rel, matched: task.matched, fun, learn, creator: creator && social },
  };
}
