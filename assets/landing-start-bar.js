// Shows the "Start for free" bar once the hero button has scrolled out of
// view, and hides it again when the closing button is on screen or passed.
(() => {
  const bar = document.getElementById("start-bar");
  const heroButton = document.querySelector(".hero-cta");
  const closingButton = document.querySelector(".closing-go .cta");
  if (!bar || !heroButton || !closingButton) return;

  const update = () => {
    const heroGone = heroButton.getBoundingClientRect().bottom < 0;
    const closingNotYet = closingButton.getBoundingClientRect().top > window.innerHeight;
    bar.classList.toggle("is-shown", heroGone && closingNotYet);
  };

  let queued = false;
  const queue = () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      update();
    });
  };

  window.addEventListener("scroll", queue, { passive: true });
  window.addEventListener("resize", queue);
  update();
})();
