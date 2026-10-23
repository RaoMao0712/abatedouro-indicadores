(function () {
  const root = document.querySelector('[data-pallet-selection]');
  if (!root) return;
  const boxes = Array.from(root.querySelectorAll('[data-caixa]'));
  const opSelectors = Array.from(root.querySelectorAll('[data-select-op]'));
  const actions = Array.from(root.querySelectorAll('[data-batch-action]'));
  const counter = root.querySelector('[data-selected-count]');
  const quantities = Array.from(root.querySelectorAll('[data-p10-quantity]'));

  function belongsTo(box, op) {
    return (box.dataset.ops || '').split(',').filter(Boolean).includes(String(op));
  }
  function sync() {
    const selected = boxes.filter(box => box.checked).length;
    if (counter) counter.textContent = selected;
    actions.forEach(action => { action.disabled = selected === 0; });
    opSelectors.forEach(selector => {
      const group = boxes.filter(box => belongsTo(box, selector.dataset.selectOp));
      const checked = group.filter(box => box.checked).length;
      selector.checked = group.length > 0 && checked === group.length;
      selector.indeterminate = checked > 0 && checked < group.length;
    });
  }
  boxes.forEach(box => box.addEventListener('change', sync));
  quantities.forEach(input => input.addEventListener('input', function () {
    const output = input.parentElement.querySelector('[data-p10-saldo]');
    if (output) output.textContent = Math.max(0, Number(input.dataset.disponivel) - Number(input.value || 0));
  }));
  opSelectors.forEach(selector => selector.addEventListener('change', function () {
    boxes.filter(box => belongsTo(box, selector.dataset.selectOp)).forEach(box => { box.checked = selector.checked; });
    sync();
  }));
  const remove = root.querySelector('[data-confirm-remove]');
  if (remove) remove.addEventListener('click', function (event) {
    if (!window.confirm('Remover as posições selecionadas deste pallet? O estoque não será alterado.')) event.preventDefault();
  });
  root.addEventListener('submit', function (event) {
    const itens = quantities.filter(input => input.value && boxes.some(box => box.value === input.name.replace('quantidade_galinhas_', '') && box.checked));
    if (!itens.length) return;
    const resumo = itens.map(input => `OP ${input.dataset.op} | ${input.dataset.apresentacao} | antes ${input.dataset.disponivel} | pallet ${input.value} | saldo ${Number(input.dataset.disponivel) - Number(input.value)} | ${input.dataset.pallet}`).join('\n');
    if (!window.confirm(`Conferência da palletização:\n${resumo}`)) event.preventDefault();
  });
  sync();
}());
