const query = new URLSearchParams(location.search);
document.getElementById("task").textContent = query.get("task") || "Your current task";
const probability = query.get("p") === null ? NaN : Number(query.get("p"));
document.getElementById("p").textContent = Number.isFinite(probability)
  ? Math.round(Math.max(0, Math.min(1, probability)) * 100) + "%" : "—";
document.getElementById("title").textContent = query.get("t") || "This page";
try { document.getElementById("url").textContent = new URL(query.get("u")).hostname; }
catch { document.getElementById("url").textContent = query.get("u") || ""; }
document.getElementById("back").onclick = () => history.go(-2);
const wrong = document.getElementById("wrong");
wrong.onclick = async () => {
  wrong.disabled = true;
  const status = document.getElementById("status");
  status.dataset.tone = "";
  status.textContent = "Saving your correction…";
  try {
    const result = await chrome.runtime.sendMessage({
      type: "override", url: query.get("u"), title: query.get("t") || "",
      task: query.get("task"), p: Number(query.get("p")),
    });
    if (!result?.ok) throw new Error(result?.error || "Could not save correction");
  } catch (error) { status.textContent = error.message; status.dataset.tone = "error"; wrong.disabled = false; }
};
