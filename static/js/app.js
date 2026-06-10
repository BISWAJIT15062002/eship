const state = {
  query: "",
  country: "",
  section: "",
  type: "",
  speed: "",
  builder: "",
  page: 1,
  pageSize: 20,
  loading: false,
};

const elements = {
  searchInput: document.getElementById("searchInput"),
  voiceSearchButton: document.getElementById("voiceSearchButton"),
  voiceSearchStatus: document.getElementById("voiceSearchStatus"),
  countryFilter: document.getElementById("countryFilter"),
  sectionFilter: document.getElementById("sectionFilter"),
  typeFilter: document.getElementById("typeFilter"),
  speedFilter: document.getElementById("speedFilter"),
  builderFilter: document.getElementById("builderFilter"),
  clearFilters: document.getElementById("clearFilters"),
  pageSize: document.getElementById("pageSize"),
  cardsGrid: document.getElementById("cardsGrid"),
  resultCount: document.getElementById("resultCount"),
  pagination: document.getElementById("pagination"),
};

const filterControls = {
  country: {
    element: elements.countryFilter,
    label: "All countries",
    valuesKey: "countries",
  },
  section: {
    element: elements.sectionFilter,
    label: "All sections",
    valuesKey: "sections",
  },
  type: {
    element: elements.typeFilter,
    label: "All types",
    valuesKey: "types",
  },
  builder: {
    element: elements.builderFilter,
    label: "All builders",
    valuesKey: "builders",
  },
};

const speedOptions = [
  { value: "20", label: "20+ knots" },
  { value: "25", label: "25+ knots" },
  { value: "28", label: "28+ knots" },
  { value: "30", label: "30+ knots" },
];

let searchTimer = 0;
let lastRequestId = 0;
let recognition = null;
let listeningForVoice = false;
let committedVoiceTranscript = "";

function buildParams() {
  const params = new URLSearchParams({
    page: String(state.page),
    page_size: String(state.pageSize),
  });

  [
    ["q", state.query],
    ["country", state.country],
    ["section", state.section],
    ["type", state.type],
    ["speed", state.speed],
    ["builder", state.builder],
  ].forEach(([key, value]) => {
    if (value) {
      params.set(key, value);
    }
  });

  return params;
}

async function fetchClasses() {
  const requestId = ++lastRequestId;
  state.loading = true;
  elements.cardsGrid.innerHTML = '<div class="empty-state">Searching Ships...</div>';

  const response = await fetch(`/api/classes?${buildParams().toString()}`);
  if (!response.ok) {
    throw new Error("Class search failed");
  }

  const data = await response.json();
  if (requestId !== lastRequestId) {
    return;
  }

  state.loading = false;
  updateFilterOptions(data.facets || {});
  render(data.items || [], Number(data.total || 0));
}

function updateFilterOptions(facets) {
  Object.entries(filterControls).forEach(([key, config]) => {
    const currentValue = state[key];
    const values = (facets[config.valuesKey] || []).filter(Boolean);

    config.element.innerHTML = [
      `<option value="">${config.label}</option>`,
      ...values.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`),
    ].join("");

    if (currentValue && values.includes(currentValue)) {
      config.element.value = currentValue;
    } else if (currentValue) {
      state[key] = "";
    }
  });

  elements.speedFilter.innerHTML = [
    '<option value="">Any speed</option>',
    ...speedOptions.map((option) => `<option value="${option.value}">${option.label}</option>`),
  ].join("");
  elements.speedFilter.value = state.speed;
}

function renderCards(items) {
  if (!items.length) {
    elements.cardsGrid.innerHTML = '<div class="empty-state">No ship classes match these filters.</div>';
    return;
  }

  elements.cardsGrid.innerHTML = items.map((item) => {
    const image = item.images && item.images.length ? item.images[0] : null;
    const imageMarkup = image
      ? `<img src="${escapeHtml(image.url)}" alt="${escapeHtml(image.alt || item.class_name)}" loading="lazy">`
      : '<span>No image</span>';

    return `
    <article class="ship-card">
      <a class="ship-card-media" href="/classes/${encodeURIComponent(item.slug)}" aria-label="View ${escapeHtml(item.class_name)} image">
        ${imageMarkup}
      </a>
      <div>
        <h2>${escapeHtml(item.class_name)}</h2>
        <dl>
          <div><dt>Country</dt><dd>${escapeHtml(item.country)}</dd></div>
          <div><dt>Section</dt><dd>${escapeHtml(item.section)}</dd></div>
          <div><dt>Type</dt><dd>${escapeHtml(item.type)}</dd></div>
          <div><dt>Builder</dt><dd>${escapeHtml(item.builder)}</dd></div>
          <div><dt>Ships</dt><dd>${item.ships.length}</dd></div>
          <div><dt>Speed</dt><dd>${item.speed_knots} knots</dd></div>
        </dl>
      </div>
      <a class="card-action" href="/classes/${encodeURIComponent(item.slug)}">View Details</a>
    </article>
  `;
  }).join("");
}

function renderPagination(totalItems) {
  const pageCount = Math.max(1, Math.ceil(totalItems / state.pageSize));
  state.page = Math.min(state.page, pageCount);

  const buttons = [];
  buttons.push(`<button type="button" data-page="${state.page - 1}" ${state.page === 1 ? "disabled" : ""}>Prev</button>`);

  const start = Math.max(1, state.page - 3);
  const end = Math.min(pageCount, state.page + 3);
  for (let page = start; page <= end; page += 1) {
    buttons.push(`<button type="button" data-page="${page}" ${page === state.page ? 'aria-current="page"' : ""}>${page}</button>`);
  }

  buttons.push(`<button type="button" data-page="${state.page + 1}" ${state.page === pageCount ? "disabled" : ""}>Next</button>`);
  elements.pagination.innerHTML = buttons.join("");
}

function render(items, totalItems) {
  const from = totalItems ? ((state.page - 1) * state.pageSize) + 1 : 0;
  const to = Math.min(state.page * state.pageSize, totalItems);

  elements.resultCount.textContent = `Showing ${from}-${to} of ${totalItems} classes`;
  renderCards(items);
  renderPagination(totalItems);
}

function refresh() {
  fetchClasses().catch(() => {
    state.loading = false;
    elements.resultCount.textContent = "Search unavailable";
    elements.cardsGrid.innerHTML = '<div class="empty-state">Data is not available right now.</div>';
    elements.pagination.innerHTML = "";
  });
}

function updateSearchQuery(value) {
  state.query = value;
  state.page = 1;
  elements.searchInput.value = value;
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(refresh, 250);
}

function previewSearchQuery(value) {
  state.query = value;
  state.page = 1;
  elements.searchInput.value = value;
}

function setFilter(key, value) {
  state[key] = value;
  state.page = 1;
  refresh();
}

function clearFilters() {
  if (recognition && listeningForVoice) {
    recognition.abort();
  }

  state.query = "";
  state.country = "";
  state.section = "";
  state.type = "";
  state.speed = "";
  state.builder = "";
  state.page = 1;

  elements.searchInput.value = "";
  setVoiceStatus("");
  refresh();
}

function setVoiceStatus(message) {
  elements.voiceSearchStatus.textContent = message;
}

function setVoiceListening(isListening) {
  listeningForVoice = isListening;
  elements.voiceSearchButton.classList.toggle("is-listening", isListening);
  elements.voiceSearchButton.setAttribute("aria-pressed", String(isListening));
  elements.voiceSearchButton.setAttribute(
    "aria-label",
    isListening ? "Stop voice search" : "Search by voice",
  );
  elements.voiceSearchButton.title = isListening ? "Listening..." : "Search by voice";
  if (isListening) {
    setVoiceStatus("Listening...");
  }
}

function getVoiceErrorMessage(errorName) {
  const messages = {
    "audio-capture": "No microphone was found.",
    "not-allowed": "Microphone permission was blocked.",
    "no-speech": "No voice detected. Try again.",
    network: "Voice recognition needs a working browser connection.",
  };

  return messages[errorName] || "Voice search could not start. Try again.";
}

function initializeVoiceSearch() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  if (!SpeechRecognition) {
    elements.voiceSearchButton.disabled = true;
    elements.voiceSearchButton.title = "Voice search is not supported in this browser";
    elements.voiceSearchButton.setAttribute("aria-label", "Voice search is not supported in this browser");
    setVoiceStatus("Voice search is not supported in this browser.");
    return;
  }

  recognition = new SpeechRecognition();
  recognition.lang = navigator.language || "en-IN";
  recognition.continuous = false;
  recognition.interimResults = true;

  recognition.addEventListener("start", () => {
    committedVoiceTranscript = "";
    setVoiceListening(true);
  });
  recognition.addEventListener("end", () => {
    setVoiceListening(false);
    if (!state.query.trim()) {
      setVoiceStatus("");
    } else if (committedVoiceTranscript) {
      setVoiceStatus(`Searching for "${committedVoiceTranscript}"`);
    } else {
      updateSearchQuery(state.query);
      setVoiceStatus(`Searching for "${state.query}"`);
    }
  });
  recognition.addEventListener("error", (event) => {
    setVoiceListening(false);
    setVoiceStatus(getVoiceErrorMessage(event.error));
  });
  recognition.addEventListener("result", (event) => {
    let finalTranscript = "";
    let interimTranscript = "";

    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const transcript = event.results[index][0].transcript.trim();
      if (event.results[index].isFinal) {
        finalTranscript = `${finalTranscript} ${transcript}`.trim();
      } else {
        interimTranscript = `${interimTranscript} ${transcript}`.trim();
      }
    }

    if (finalTranscript) {
      committedVoiceTranscript = finalTranscript;
      updateSearchQuery(finalTranscript);
      return;
    }

    if (interimTranscript) {
      previewSearchQuery(interimTranscript);
    }
  });

  elements.voiceSearchButton.addEventListener("click", () => {
    if (listeningForVoice) {
      recognition.stop();
      return;
    }

    elements.searchInput.focus();
    setVoiceStatus("Allow microphone access when your browser asks.");
    try {
      recognition.start();
    } catch {
      setVoiceListening(false);
      setVoiceStatus("Voice search is already starting. Try again.");
    }
  });
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[character]));
}

elements.searchInput.addEventListener("input", (event) => {
  updateSearchQuery(event.target.value);
});
elements.countryFilter.addEventListener("change", (event) => setFilter("country", event.target.value));
elements.sectionFilter.addEventListener("change", (event) => setFilter("section", event.target.value));
elements.typeFilter.addEventListener("change", (event) => setFilter("type", event.target.value));
elements.speedFilter.addEventListener("change", (event) => setFilter("speed", event.target.value));
elements.builderFilter.addEventListener("change", (event) => setFilter("builder", event.target.value));
elements.clearFilters.addEventListener("click", clearFilters);
elements.pageSize.addEventListener("change", (event) => {
  state.pageSize = Number(event.target.value);
  state.page = 1;
  refresh();
});

elements.pagination.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-page]");
  if (!button || button.disabled) {
    return;
  }
  state.page = Number(button.dataset.page);
  refresh();
  window.scrollTo({ top: 0, behavior: "smooth" });
});

initializeVoiceSearch();
refresh();
