const task = document.getElementById("task");
const status = document.getElementById("status");
const save = document.getElementById("save");
chrome.storage.local.get("last", ({ last }) => {
  if (last) document.getElementById("last").textContent = `${last.lock ? "Paused" : "Allowed"} · ${last.title || last.url}`;
});
fetch("http://127.0.0.1:8790", { signal: AbortSignal.timeout(5000) })
  .then(response => {
    if (!response.ok) throw new Error("Gate server unavailable");
    return response.json();
  })
  .then(state => {
    task.value = state.task;
    const memory = state.memory;
    document.getElementById("memory").textContent = !memory?.enabled ? "Personal memory is off."
      : memory.available ? `Connected for ${memory.owner_id}. Saved context informs your page checks.` : "Temporarily unavailable. Page checks still work.";
    document.getElementById("memory-dot").dataset.connected = String(Boolean(memory?.enabled && memory.available));
  })
  .catch(() => {
    status.textContent = "Start Floodgate to set your focus.";
    status.dataset.tone = "error";
    document.getElementById("memory").textContent = "Waiting for Floodgate to connect.";
  });
document.getElementById("focus-form").onsubmit = async event => {
  event.preventDefault();
  save.disabled = true;
  status.dataset.tone = "";
  status.textContent = "Saving your focus…";
  try {
    const result = await chrome.runtime.sendMessage({ type: "setTask", task: task.value });
    if (!result?.ok) throw new Error(result?.error || "Could not save task");
    status.textContent = result.memory?.enabled && !result.memory.available
      ? "Focus saved. Personal memory is unavailable." : "Focus saved. You’re ready for your next visit.";
  } catch (error) { status.textContent = error.message; status.dataset.tone = "error"; }
  finally { save.disabled = false; }
};
task.addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    if (!save.disabled) document.getElementById("focus-form").requestSubmit();
  }
});
