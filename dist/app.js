document.documentElement.classList.add('js');
const menuButton = document.querySelector('.menu-toggle');
const navigation = document.querySelector('#site-nav');
const mobileQuery = window.matchMedia('(max-width: 760px)');
menuButton.hidden = false;

function closeMenu(returnFocus = false) {
  menuButton.setAttribute('aria-expanded', 'false');
  navigation.classList.remove('is-open');
  if (returnFocus) menuButton.focus();
}

menuButton.addEventListener('click', () => {
  const opening = menuButton.getAttribute('aria-expanded') !== 'true';
  menuButton.setAttribute('aria-expanded', String(opening));
  navigation.classList.toggle('is-open', opening);
});
navigation.addEventListener('click', event => {
  if (event.target.closest('a')) closeMenu();
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && menuButton.getAttribute('aria-expanded') === 'true') closeMenu(true);
});
document.addEventListener('click', event => {
  if (mobileQuery.matches && !event.target.closest('.header-inner')) closeMenu();
});
mobileQuery.addEventListener('change', () => closeMenu());

// These are authored examples, not requests to an AI service.
const scenarios = {
  create: ['“Turn my project notes into a clear one-page proposal.”', 'An editable proposal, ready for your review.', 'Identify the audience, key points and missing information.', 'Ask which notes may be read and where the draft may be saved.', 'Use available document tools to structure and draft the proposal.', 'Check the draft against the brief and report what still needs your input.'],
  research: ['“Compare these three options and explain the trade-offs.”', 'A comparison with sources, gaps and a clear summary.', 'Define the criteria that matter to you and the sources to consult.', 'Confirm access to your material and permission for any external research.', 'Gather evidence, compare the options and organize the findings.', 'Link conclusions to sources and flag missing or conflicting evidence.'],
  organize: ['“Turn these scattered notes into an actionable project plan.”', 'A structured plan with tasks, dependencies and open questions.', 'Identify the goal, group related notes and surface unanswered questions.', 'Confirm which notes are in scope and where the plan should be saved.', 'Arrange the work into steps using available planning and document tools.', 'Check the plan against your notes; leave unconfirmed dates and owners open.']
};
function setScenario(key) {
  if (!scenarios[key]) return;
  ['request', 'result', 'plan', 'permission', 'coordinate', 'verify'].forEach((field, i) => {
    document.getElementById(`example-${field}`).textContent = scenarios[key][i];
  });
  document.querySelectorAll('[data-scenario]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.scenario === key)));
}
document.querySelectorAll('[data-scenario]').forEach(button => button.addEventListener('click', () => setScenario(button.dataset.scenario)));
document.querySelectorAll('[data-example-link]').forEach(link => link.addEventListener('click', () => setScenario(link.dataset.exampleLink)));

const tabs = [...document.querySelectorAll('[role="tab"]')];
const panels = [...document.querySelectorAll('[role="tabpanel"]')];
const hashPanels = {features:'idea',command:'idea',how:'approach',roadmap:'roadmap',questions:'questions',explore:'idea'};
function selectPanel(key, focus = false) {
  tabs.forEach(tab => {
    const selected = tab.dataset.panel === key;
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
    if (selected && focus) tab.focus();
  });
  panels.forEach(panel => panel.hidden = panel.id !== `panel-${key}`);
}
function activateTab(tab) {
  selectPanel(tab.dataset.panel);
  history.replaceState(null, '', `#${tab.dataset.panel === 'idea' ? 'features' : tab.dataset.panel === 'approach' ? 'how' : tab.dataset.panel}`);
  document.getElementById('explore').scrollIntoView({block:'start',behavior:'instant'});
}
tabs.forEach((tab, index) => {
  tab.addEventListener('click', () => activateTab(tab));
  tab.addEventListener('keydown', event => {
    let target;
    if (event.key === 'ArrowRight') target = (index + 1) % tabs.length;
    if (event.key === 'ArrowLeft') target = (index + tabs.length - 1) % tabs.length;
    if (event.key === 'Home') target = 0;
    if (event.key === 'End') target = tabs.length - 1;
    if (target !== undefined) {
      event.preventDefault();
      tabs[target].focus();
      activateTab(tabs[target]);
    }
  });
});
document.querySelectorAll('a[href^="#"]').forEach(link => link.addEventListener('click', () => {
  const key = hashPanels[link.hash.slice(1)];
  if (key) selectPanel(key);
}));
window.addEventListener('hashchange', () => {
  const key = hashPanels[location.hash.slice(1)];
  if (key) selectPanel(key);
});
selectPanel(hashPanels[location.hash.slice(1)] || 'idea');
