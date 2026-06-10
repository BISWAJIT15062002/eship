const modal = document.getElementById("imageModal");
const modalImage = document.getElementById("modalImage");
const closeModal = document.getElementById("closeModal");

function openModal(src, alt) {
  modalImage.src = src;
  modalImage.alt = alt;
  modal.classList.add("is-open");
  modal.setAttribute("aria-hidden", "false");
}

function hideModal() {
  modal.classList.remove("is-open");
  modal.setAttribute("aria-hidden", "true");
  modalImage.src = "";
}

document.querySelectorAll(".gallery-item").forEach((button) => {
  button.addEventListener("click", () => {
    openModal(button.dataset.fullImage, button.dataset.alt);
  });
});

closeModal.addEventListener("click", hideModal);

modal.addEventListener("click", (event) => {
  if (event.target === modal) {
    hideModal();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && modal.classList.contains("is-open")) {
    hideModal();
  }
});
