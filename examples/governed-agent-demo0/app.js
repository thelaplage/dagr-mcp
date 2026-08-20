document.addEventListener('DOMContentLoaded', async () => {
  const response = await fetch('fixtures/governed_run.json');
  const scenario = await response.json();

  const agent = document.getElementById('agent');
  agent.innerHTML += `<p>${scenario.question}</p>`;

  scenario.steps.forEach((step) => {
    const section = document.createElement('section');
    section.innerHTML = `<h3>${step.phase}</h3><pre>${JSON.stringify(step, null, 2)}</pre>`;
    agent.appendChild(section);
  });

  document.getElementById('evidence').innerHTML += '<p>DISCOVERED / FETCHED / CITED / RELIED-UPON remain separate.</p>';
  document.getElementById('graph').innerHTML += '<p>co_reference is not supported_by. Temporal order is not causation.</p>';
  document.getElementById('projection').innerHTML += '<p>Projection resurrection compares declared reconstruction output.</p>';
  document.getElementById('recovery').innerHTML += '<p>Recovery uses governed references, not hidden process memory.</p>';
});
