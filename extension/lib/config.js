// Shared constants: the question the model answers, modes, default settings and domain priors.

// Same wording as floodgate/gate_server.py and floodgate/prep_gate_dataset.py, so labels become training rows as-is.
export const QUESTION = "Is this page a distraction from the stated task?";

// blockAt / nudgeAt are P(distraction) thresholds. Between them the page stays open and Floodgate asks you.
export const MODES = {
  focus: {
    label: "Focus",
    blockAt: 0.7,
    nudgeAt: 0.5,
    hint: "Only pages about your task get through.",
  },
  research: {
    label: "Research",
    blockAt: 0.8,
    nudgeAt: 0.55,
    hint: "More room for learning material near your task.",
  },
  creator: {
    label: "Creator",
    blockAt: 0.85,
    nudgeAt: 0.55,
    hint: "Trends, memes and viral videos count as work.",
    profile: "I am a content creator. Keeping up with trends, memes, viral videos and what other creators post is part of my job.",
  },
  break: {
    label: "Break",
    blockAt: Infinity,
    nudgeAt: Infinity,
    hint: "Nothing is blocked. Visits are still scored and logged.",
  },
};

// Never gated: your own tools, sign-in pages and the gate servers themselves.
export const ALWAYS_ALLOW = ["localhost", "127.0.0.1", "accounts.google.com", "chromewebstore.google.com", "chrome.google.com"];

export const DEFAULT_SETTINGS = {
  task: "",
  profile: "",
  mode: "focus",
  provider: "heuristic", // id of the decision provider (see providers/index.js)
  providerSettings: {}, // { [providerId]: { key: value } }
  enrichers: {}, // { [providerId]: true } for providers that add context (GBrain, ...)
  allowDomains: [], // your "always allow" list
  blockDomains: [], // your "always block" list
  pausedUntil: 0,
  recentTasks: [],
  sendLabels: true, // forward labels to providers that learn from them (gate server /override, ...)
  onboarded: false,
};

// Domain priors for the offline classifier. The model and your labels override these.
export const DISTRACTION_DOMAINS = [
  "youtube.com", "youtu.be", "reddit.com", "x.com", "twitter.com", "instagram.com", "tiktok.com", "facebook.com",
  "netflix.com", "twitch.tv", "9gag.com", "hulu.com", "disneyplus.com", "primevideo.com", "max.com", "crunchyroll.com",
  "pinterest.com", "snapchat.com", "threads.net", "tumblr.com", "imgur.com", "espn.com", "buzzfeed.com", "kick.com",
  "mangadex.org", "webtoons.com", "store.steampowered.com", "roblox.com", "amazon.com", "ebay.com", "bsky.app",
];

// Platforms where creators research trends (creator mode treats entertainment here as work).
export const SOCIAL_DOMAINS = [
  "youtube.com", "youtu.be", "tiktok.com", "instagram.com", "x.com", "twitter.com", "reddit.com", "threads.net",
  "facebook.com", "twitch.tv", "9gag.com", "pinterest.com", "snapchat.com", "tumblr.com", "bsky.app", "kick.com",
];

export const WORK_DOMAINS = [
  "github.com", "gitlab.com", "stackoverflow.com", "stackexchange.com", "docs.google.com", "drive.google.com",
  "mail.google.com", "calendar.google.com", "meet.google.com", "notion.so", "notion.site", "linear.app", "figma.com",
  "vercel.com", "netlify.com", "arxiv.org", "huggingface.co", "readthedocs.io", "developer.mozilla.org", "npmjs.com",
  "pypi.org", "claude.ai", "chatgpt.com", "anthropic.com", "river.ai", "typesafe.ai", "gbrain.io", "superset.sh",
  "memorable.sh", "ufo.ai", "ycombinator.com", "slack.com", "atlassian.net", "overleaf.com", "colab.research.google.com",
  "kaggle.com", "aws.amazon.com", "console.cloud.google.com", "portal.azure.com", "cloudflare.com", "supabase.com",
];

export const SEARCH_DOMAINS = ["google.com", "bing.com", "duckduckgo.com", "perplexity.ai", "search.brave.com", "kagi.com"];

export const REFERENCE_DOMAINS = ["wikipedia.org", "medium.com", "substack.com", "dev.to", "news.ycombinator.com", "quora.com"];
