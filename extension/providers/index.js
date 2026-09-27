// Provider registry. To add yours: copy _template.js, import it here and append it to PROVIDERS.
import floodgateGate from "./floodgate-gate.js";
import heuristic from "./heuristic.js";
import systemone from "./systemone.js";
import gbrain from "./gbrain.js";
import memorable from "./memorable.js";

export const PROVIDERS = [heuristic, floodgateGate, systemone, gbrain, memorable];

export const byId = (id) => PROVIDERS.find((p) => p.id === id);

/** The provider's settings with defaults filled in from its `settings` schema. */
export function providerConfig(provider, settings) {
  const saved = settings.providerSettings?.[provider.id] || {};
  return Object.fromEntries((provider.settings || []).map((f) => [f.key, saved[f.key] ?? f.default]));
}
