document.addEventListener('DOMContentLoaded', async () => {
  const response = await fetch('scenario.json');
  const scenario = await response.json();
  const list = scenario.steps.map(step => `<li>${step.name}: ${step.status}</li>`).join('');
  document.getElementById('agent').innerHTML += `<ul>${list}</ul>`;
  document.getElementById('evidence').innerHTML += '<p>DISCOVERED / FETCHED / CITED / RELIED-UPON remain separate.</p>';
  document.getElementById('graph').innerHTML += '<p>co_reference is not supported_by. Temporal order is not causation.</p>';
  document.getElementById('projection').innerHTML += '<p>Projection resurrection uses declared inputs only.</p>';
  document.getElementById('recovery').innerHTML += '<p>Recovery uses governed references, not hidden memory.</p>';
});
