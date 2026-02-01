async function moveTask(id, status) {
  await fetch(`/move/${id}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status })
  });
  // 簡単にするためリロード（高速化したいならDOMだけ更新）
  location.reload();
}

async function deleteTask(id) {
  await fetch(`/delete/${id}`, { method: "POST" });
  location.reload();
}

let draggingId = null;

document.querySelectorAll(".card[draggable='true']").forEach(card => {
  card.addEventListener("dragstart", (e) => {
    draggingId = card.dataset.id;
    card.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
  });
  card.addEventListener("dragend", () => {
    card.classList.remove("dragging");
    draggingId = null;
  });
});

document.querySelectorAll(".dropzone").forEach(zone => {
  zone.addEventListener("dragover", (e) => {
    e.preventDefault();
  });
  zone.addEventListener("drop", async (e) => {
    e.preventDefault();
    const status = zone.dataset.status;
    if (!draggingId) return;
    await moveTask(draggingId, status);
  });
});


document.addEventListener("click", async (e) => {
  const moveBtn = e.target.closest("button[data-move]");
  if (moveBtn) {
    const id = moveBtn.dataset.move;
    const to = moveBtn.dataset.to;
    await moveTask(id, to);
    return;
  }

  const delBtn = e.target.closest("button[data-delete]");
  if (delBtn) {
    const id = delBtn.dataset.delete;
    await deleteTask(id);
    return;
  }
});