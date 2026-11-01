// Controlled benchmark fixture. Deliberately unsafe; never ship to production.
function renderUser(input) {
  document.querySelector('#user').innerHTML = input;
}

module.exports = { renderUser };
