export const ViewerMode = Object.freeze({
  ONE: 'one',
  ONE_TWO: 'one-two',
  TWO_ONE: 'two-one',
  SCROLL: 'scroll',
});

const clamp = (value, min, max) => Math.min(Math.max(value, min), max);
const escapeAttribute = (value) => String(value).replace(/[&<>"']/g, (character) => ({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
})[character]);

/**
 * RIDI PC viewer compatible page grouping.
 * All page numbers in this public API are 1-based.
 */
export function getPageGroup(mode, requestedPage, totalPages) {
  const total = Math.max(1, Number(totalPages) || 1);
  const requested = clamp(Number(requestedPage) || 1, 1, total);

  if (mode === ViewerMode.ONE || mode === ViewerMode.SCROLL) {
    return [requested];
  }

  // Both spread modes keep the cover by itself; their only difference is visual order.
  if (mode === ViewerMode.ONE_TWO || mode === ViewerMode.TWO_ONE) {
    if (requested === 1) return [null, 1];
    const first = requested % 2 === 1 ? requested - 1 : requested;
    return [first, first + 1 <= total ? first + 1 : null];
  }

  throw new Error(`Unknown viewer mode: ${mode}`);
}

export function getModePositions(mode, totalPages) {
  const total = Math.max(1, Number(totalPages) || 1);

  if (mode === ViewerMode.ONE || mode === ViewerMode.SCROLL) {
    return Array.from({ length: total }, (_, index) => index + 1);
  }

  if (mode === ViewerMode.ONE_TWO || mode === ViewerMode.TWO_ONE) {
    return [1, ...Array.from({ length: Math.ceil((total - 1) / 2) }, (_, index) => index * 2 + 2)];
  }

  return [1];
}

function normalizePageForMode(mode, page, totalPages) {
  return getPageGroup(mode, page, totalPages).find((value) => value !== null) ?? 1;
}

function normalizePageItem(item, index) {
  if (typeof item === 'string') return { src: item, alt: `${index + 1}페이지` };
  return { src: item.src, alt: item.alt || `${index + 1}페이지` };
}

export class RidiStyleViewer extends EventTarget {
  constructor({
    root,
    pages,
    title = '',
    initialPage = 1,
    initialMode = ViewerMode.TWO_ONE,
    readingDirection = 'rtl',
  }) {
    super();
    this.root = typeof root === 'string' ? document.querySelector(root) : root;
    if (!this.root) throw new Error('Viewer root element was not found.');

    this.pages = pages.map(normalizePageItem);
    if (!this.pages.length) throw new Error('At least one page is required.');

    this.title = title;
    this.totalPages = this.pages.length;
    this.mode = initialMode;
    this.currentPage = normalizePageForMode(initialMode, initialPage, this.totalPages);
    this.readingDirection = readingDirection;
    this.controlsVisible = true;
    this.zoom = 1;
    this.observer = null;
    this.hideTimer = null;

    this.mount();
  }

  mount() {
    this.root.classList.add('rv-host');
    this.root.innerHTML = `
      <section class="rv-shell" data-mode="${this.mode}" data-controls="visible">
        <header class="rv-toolbar rv-toolbar--top">
          <button class="rv-icon-button" type="button" data-action="close" aria-label="뷰어 닫기">×</button>
          <strong class="rv-title"></strong>
          <div class="rv-mode-group" role="group" aria-label="페이지 설정">
            <button type="button" data-mode="one">한쪽</button>
            <button type="button" data-mode="one-two">1→2</button>
            <button type="button" data-mode="two-one">2←1</button>
            <button type="button" data-mode="scroll">스크롤</button>
          </div>
        </header>

        <main class="rv-viewport">
          <div class="rv-pages" aria-live="polite"></div>
          <div class="rv-tap-zones" aria-hidden="true">
            <button type="button" data-action="previous" tabindex="-1">‹</button>
            <button type="button" data-action="toggle-controls" tabindex="-1">☰</button>
            <button type="button" data-action="next" tabindex="-1">›</button>
          </div>
        </main>

        <footer class="rv-toolbar rv-toolbar--bottom">
          <button class="rv-icon-button" type="button" data-action="first" aria-label="첫 페이지">|‹</button>
          <input class="rv-progress" type="range" min="0" step="1" aria-label="페이지 이동">
          <output class="rv-page-number"></output>
          <button class="rv-icon-button" type="button" data-action="last" aria-label="마지막 페이지">›|</button>
        </footer>
      </section>
    `;

    this.shell = this.root.querySelector('.rv-shell');
    this.pagesElement = this.root.querySelector('.rv-pages');
    this.progressElement = this.root.querySelector('.rv-progress');
    this.pageNumberElement = this.root.querySelector('.rv-page-number');
    this.root.querySelector('.rv-title').textContent = this.title;

    this.root.addEventListener('click', this.handleClick);
    this.progressElement.addEventListener('input', this.handleProgress);
    this.root.addEventListener('pointermove', this.scheduleControlsHide);
    this.root.addEventListener('wheel', this.handleWheel, { passive: false });
    document.addEventListener('keydown', this.handleKeyDown);

    this.render();
    this.scheduleControlsHide();
  }

  destroy() {
    this.observer?.disconnect();
    clearTimeout(this.hideTimer);
    this.root.removeEventListener('click', this.handleClick);
    this.progressElement.removeEventListener('input', this.handleProgress);
    this.root.removeEventListener('pointermove', this.scheduleControlsHide);
    this.root.removeEventListener('wheel', this.handleWheel);
    document.removeEventListener('keydown', this.handleKeyDown);
    this.root.replaceChildren();
    this.root.classList.remove('rv-host');
  }

  handleClick = (event) => {
    const button = event.target.closest('button');
    if (!button || !this.root.contains(button)) return;

    if (button.dataset.mode) {
      this.setMode(button.dataset.mode);
      return;
    }

    const actions = {
      first: () => this.first(),
      last: () => this.last(),
      previous: () => this.previous(),
      next: () => this.next(),
      'toggle-controls': () => this.toggleControls(),
      close: () => this.dispatchEvent(new CustomEvent('close')),
    };
    actions[button.dataset.action]?.();
  };

  handleProgress = (event) => {
    const positions = getModePositions(this.mode, this.totalPages);
    this.goToPage(positions[Number(event.target.value)] || 1);
  };

  handleKeyDown = (event) => {
    if (!this.root.isConnected) return;
    if (event.key === 'ArrowRight' || event.key === ' ' || event.key === 'PageDown') {
      event.preventDefault();
      this.next();
    } else if (event.key === 'ArrowLeft' || event.key === 'PageUp') {
      event.preventDefault();
      this.previous();
    } else if (event.key === 'Enter') {
      event.preventDefault();
      this.toggleControls();
    } else if (event.key === 'Escape') {
      this.zoom = 1;
      this.applyZoom();
    } else if (event.key === 'Home') {
      this.first();
    } else if (event.key === 'End') {
      this.last();
    }
  };

  handleWheel = (event) => {
    if (!event.ctrlKey) return;
    event.preventDefault();
    this.zoom = clamp(this.zoom + (event.deltaY < 0 ? 0.1 : -0.1), 0.5, 3);
    this.applyZoom();
  };

  scheduleControlsHide = () => {
    this.setControlsVisible(true);
    clearTimeout(this.hideTimer);
    this.hideTimer = setTimeout(() => this.setControlsVisible(false), 2100);
  };

  setControlsVisible(visible) {
    this.controlsVisible = visible;
    this.shell.dataset.controls = visible ? 'visible' : 'hidden';
  }

  toggleControls() {
    this.setControlsVisible(!this.controlsVisible);
  }

  setMode(mode) {
    if (!Object.values(ViewerMode).includes(mode) || mode === this.mode) return;
    this.mode = mode;
    this.currentPage = normalizePageForMode(mode, this.currentPage, this.totalPages);
    this.zoom = 1;
    this.render();
    this.emitChange('modechange');
  }

  goToPage(page, { behavior = 'auto' } = {}) {
    const nextPage = normalizePageForMode(this.mode, page, this.totalPages);
    this.currentPage = nextPage;

    if (this.mode === ViewerMode.SCROLL) {
      this.pagesElement.querySelector(`[data-page="${nextPage}"]`)?.scrollIntoView({ behavior, block: 'start' });
      this.updateControls();
    } else {
      this.renderPaged();
      this.updateControls();
    }
    this.emitChange('pagechange');
  }

  first() {
    this.goToPage(1, { behavior: this.mode === ViewerMode.SCROLL ? 'smooth' : 'auto' });
  }

  last() {
    const positions = getModePositions(this.mode, this.totalPages);
    this.goToPage(positions.at(-1), { behavior: this.mode === ViewerMode.SCROLL ? 'smooth' : 'auto' });
  }

  previous() {
    if (this.mode === ViewerMode.SCROLL) {
      this.goToPage(this.currentPage - 1, { behavior: 'smooth' });
      return;
    }
    const positions = getModePositions(this.mode, this.totalPages);
    const index = Math.max(0, positions.indexOf(this.currentPage) - 1);
    this.goToPage(positions[index]);
  }

  next() {
    if (this.mode === ViewerMode.SCROLL) {
      this.goToPage(this.currentPage + 1, { behavior: 'smooth' });
      return;
    }
    const positions = getModePositions(this.mode, this.totalPages);
    const index = Math.min(positions.length - 1, positions.indexOf(this.currentPage) + 1);
    this.goToPage(positions[index]);
  }

  render() {
    this.shell.dataset.mode = this.mode;
    this.observer?.disconnect();
    if (this.mode === ViewerMode.SCROLL) this.renderScroll();
    else this.renderPaged();
    this.updateControls();
  }

  renderPaged() {
    const logicalPages = getPageGroup(this.mode, this.currentPage, this.totalPages);
    const visualPages = this.mode === ViewerMode.TWO_ONE ? [...logicalPages].reverse() : logicalPages;

    this.pagesElement.className = 'rv-pages rv-pages--paged';
    this.pagesElement.innerHTML = visualPages.map((pageNumber) => {
      if (pageNumber === null) return '<div class="rv-page rv-page--blank" aria-hidden="true"></div>';
      const page = this.pages[pageNumber - 1];
      return `<figure class="rv-page" data-page="${pageNumber}"><img src="${escapeAttribute(page.src)}" alt="${escapeAttribute(page.alt)}"></figure>`;
    }).join('');
    this.applyZoom();
  }

  renderScroll() {
    this.pagesElement.className = 'rv-pages rv-pages--scroll';
    this.pagesElement.innerHTML = this.pages.map((page, index) => `
      <figure class="rv-page" data-page="${index + 1}">
        <img src="${escapeAttribute(page.src)}" alt="${escapeAttribute(page.alt)}" loading="${index < 3 ? 'eager' : 'lazy'}">
      </figure>
    `).join('');

    this.observer = new IntersectionObserver((entries) => {
      const visible = entries.filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (!visible) return;
      const page = Number(visible.target.dataset.page);
      if (page !== this.currentPage) {
        this.currentPage = page;
        this.updateControls();
        this.emitChange('pagechange');
      }
    }, { root: this.pagesElement, threshold: [0.25, 0.5, 0.75] });

    this.pagesElement.querySelectorAll('[data-page]').forEach((page) => this.observer.observe(page));
    requestAnimationFrame(() => {
      this.pagesElement.querySelector(`[data-page="${this.currentPage}"]`)?.scrollIntoView({ block: 'start' });
    });
  }

  updateControls() {
    const positions = getModePositions(this.mode, this.totalPages);
    const currentPosition = Math.max(0, positions.indexOf(this.currentPage));
    this.progressElement.max = String(positions.length - 1);
    this.progressElement.value = String(currentPosition);

    const pages = getPageGroup(this.mode, this.currentPage, this.totalPages).filter(Boolean);
    const visibleLabel = pages.length === 2 ? `${pages[0]}-${pages[1]}` : String(pages[0]);
    this.pageNumberElement.value = `${visibleLabel} / ${this.totalPages}`;
    this.pageNumberElement.textContent = `${visibleLabel} / ${this.totalPages}`;

    this.root.querySelectorAll('[data-mode]').forEach((button) => {
      const active = button.dataset.mode === this.mode;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-pressed', String(active));
    });

    this.root.querySelector('[data-action="first"]').disabled = currentPosition === 0;
    this.root.querySelector('[data-action="previous"]').disabled = currentPosition === 0;
    this.root.querySelector('[data-action="last"]').disabled = currentPosition === positions.length - 1;
    this.root.querySelector('[data-action="next"]').disabled = currentPosition === positions.length - 1;
  }

  applyZoom() {
    this.pagesElement.style.setProperty('--rv-zoom', this.zoom);
  }

  emitChange(type) {
    this.dispatchEvent(new CustomEvent(type, {
      detail: {
        mode: this.mode,
        currentPage: this.currentPage,
        visiblePages: getPageGroup(this.mode, this.currentPage, this.totalPages).filter(Boolean),
        totalPages: this.totalPages,
      },
    }));
  }
}
