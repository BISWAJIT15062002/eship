const menuToggle = document.getElementById("menuToggle");
const topMenu = document.getElementById("topMenu");

if (menuToggle && topMenu) {
  menuToggle.addEventListener("click", () => {
    const isOpen = topMenu.classList.toggle("is-open");
    menuToggle.setAttribute("aria-expanded", String(isOpen));
  });

  document.addEventListener("click", (event) => {
    if (!event.target.closest(".menu-wrap")) {
      topMenu.classList.remove("is-open");
      menuToggle.setAttribute("aria-expanded", "false");
    }
  });
}

const heroSlides = document.querySelectorAll(".hero-slider span");
let activeHeroSlide = 0;

function showHeroSlide(index) {
  heroSlides.forEach((slide, slideIndex) => {
    slide.classList.toggle("is-active", slideIndex === index);
  });
}

if (heroSlides.length) {
  showHeroSlide(activeHeroSlide);
  window.setInterval(() => {
    activeHeroSlide = (activeHeroSlide + 1) % heroSlides.length;
    showHeroSlide(activeHeroSlide);
  }, 4200);
}
