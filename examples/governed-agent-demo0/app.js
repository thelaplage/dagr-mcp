document.addEventListener('DOMContentLoaded', async () => {
  const response = await fetch('fixtures/governed_artifacts.json');
  const data = await response.json();

  document.getElementById('agent').innerHTML += `<pre>${JSON.stringify(data.scenario, null, 2)}</pre>`;
  document.getElementById('evidence').innerHTML += `<pre>${JSON.stringify(data.evidence, null, 2)}</pre>`;
  document.getElementById('graph').innerHTML += `<pre>${data.graph.edge_rules.join('\n')}</pre>`;
  document.getElementById('projection').innerHTML += `<pre>${JSON.stringify(data.projection, null, 2)}</pre>`;
  document.getElementById('recovery').innerHTML += `<pre>${JSON.stringify(data.recovery, null, 2)}</pre>`;
  document.getElementById('limits').innerHTML += '<p>No truth, admission, authentication, or hidden-memory claims.</p>';
});
