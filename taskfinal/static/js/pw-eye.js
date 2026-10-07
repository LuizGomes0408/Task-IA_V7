/* Olho para mostrar/ocultar senha — aplica em TODO campo input[type=password],
   inclusive os criados depois (modais, etc.). */
(function(){
  'use strict';
  var EYE = '<i class="fa-solid fa-eye" aria-hidden="true"></i>';
  var EYE_OFF = '<i class="fa-solid fa-eye-slash" aria-hidden="true"></i>';

  function wrap(inp){
    if(inp.dataset.eye) return;
    inp.dataset.eye = '1';
    var w = document.createElement('div');
    w.className = 'pw-wrap';
    /* se o input já está dentro de .iw (ícone à esquerda), usa ele como base */
    var host = inp.parentNode;
    if(host.classList && host.classList.contains('iw')){
      host.classList.add('has-eye');
      w = host;
    } else {
      host.insertBefore(w, inp);
      w.appendChild(inp);
    }
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'pw-eye';
    b.innerHTML = EYE;
    b.setAttribute('aria-label', 'Mostrar senha');
    b.setAttribute('aria-pressed', 'false');
    b.addEventListener('click', function(e){
      e.preventDefault(); e.stopPropagation();
      var show = inp.type === 'password';
      inp.type = show ? 'text' : 'password';
      b.innerHTML = show ? EYE_OFF : EYE;
      b.setAttribute('aria-label', show ? 'Ocultar senha' : 'Mostrar senha');
      b.setAttribute('aria-pressed', String(show));
      inp.focus();
    });
    w.appendChild(b);
  }
  function scan(){ document.querySelectorAll('input[type=password]').forEach(wrap); }
  function init(){
    scan();
    new MutationObserver(scan).observe(document.body, {childList:true, subtree:true});
  }
  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
