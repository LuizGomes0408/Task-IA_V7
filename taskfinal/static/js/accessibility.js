/* ═══════════════════════════════════════════════════════════════════════
   ACESSIBILIDADE — TaskAI
   Painel flutuante com: tamanho de fonte, alto contraste, sublinhar links,
   reduzir animações, leitura da página em voz alta (Web Speech API) e
   tradução para Libras (widget oficial do governo — VLibras).
   Preferências salvas no localStorage do navegador da pessoa.
   ═══════════════════════════════════════════════════════════════════════ */
(function(){
  'use strict';

  var KEY = 'taskai-a11y';
  function loadPrefs(){
    try{ return Object.assign({fs:0, contrast:false, underline:false, reduceMotion:false, libras:false}, JSON.parse(localStorage.getItem(KEY)||'{}')); }
    catch(e){ return {fs:0, contrast:false, underline:false, reduceMotion:false, libras:false}; }
  }
  function savePrefs(p){ try{ localStorage.setItem(KEY, JSON.stringify(p)); }catch(e){} }

  var prefs = loadPrefs();
  var speaking = false;

  function applyPrefs(){
    document.body.classList.remove('a11y-fs-1','a11y-fs-2','a11y-fs-3');
    if(prefs.fs > 0) document.body.classList.add('a11y-fs-' + prefs.fs);
    document.documentElement.setAttribute('data-a11y-contrast', prefs.contrast ? 'on' : 'off');
    document.body.classList.toggle('a11y-underline', !!prefs.underline);
    document.body.classList.toggle('a11y-reduce-motion', !!prefs.reduceMotion);
    if(prefs.libras) loadVLibras();
    var w = document.querySelector('div[vw]');
    if(w) w.style.display = prefs.libras ? '' : 'none';
  }

  /* ── Libras (VLibras — widget público do governo federal) ── */
  var vlibrasLoaded = false;
  function loadVLibras(){
    if(vlibrasLoaded) return;
    vlibrasLoaded = true;
    var wrap = document.createElement('div');
    wrap.setAttribute('vw', '');
    wrap.className = 'enabled';
    wrap.innerHTML =
      '<div vw-access-button class="active"></div>' +
      '<div vw-plugin-wrapper><div class="vw-plugin-top-wrapper"></div></div>';
    document.body.appendChild(wrap);
    var s = document.createElement('script');
    s.src = 'https://vlibras.gov.br/app/vlibras-plugin.js';
    s.onload = function(){
      try{ new window.VLibras.Widget('https://vlibras.gov.br/app'); }
      catch(e){ /* se o serviço do governo estiver fora do ar, falha silenciosamente */ }
    };
    s.onerror = function(){ toastSafe('Não foi possível carregar o VLibras agora. Tente novamente mais tarde.'); };
    document.body.appendChild(s);
  }
  function toastSafe(msg){ if(typeof toast === 'function') toast(msg, 'err'); }

  /* ── Leitura em voz alta (Web Speech API) — para pessoas com baixa visão ── */
  function pageText(){
    var main = document.querySelector('main.page') || document.querySelector('.lc') || document.body;
    return main.innerText.replace(/\s+/g,' ').trim();
  }
  function toggleRead(btn){
    if(!('speechSynthesis' in window)){
      toastSafe('Seu navegador não tem suporte à leitura em voz alta.');
      return;
    }
    if(speaking){
      window.speechSynthesis.cancel();
      speaking = false;
      setReadBtnState(btn, false);
      return;
    }
    var text = pageText();
    if(!text){ toastSafe('Nada para ler nesta página.'); return; }
    var utter = new SpeechSynthesisUtterance(text);
    utter.lang = 'pt-BR';
    utter.rate = 1;
    utter.onend = function(){ speaking = false; setReadBtnState(btn, false); };
    utter.onerror = function(){ speaking = false; setReadBtnState(btn, false); };
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utter);
    speaking = true;
    setReadBtnState(btn, true);
  }
  function setReadBtnState(btn, on){
    if(!btn) return;
    btn.classList.toggle('reading', on);
    btn.innerHTML = on
      ? '<i class="fa-solid fa-stop"></i> Parar leitura'
      : '<i class="fa-solid fa-volume-high"></i> Ler esta página em voz alta';
  }

  /* ── Torna o botão arrastável (mouse e toque) — posição salva por navegador ── */
  var POS_KEY = 'taskai-a11y-btn-pos';
  function makeDraggable(el, onDragEnd){
    var dragging = false, moved = false, startX = 0, startY = 0, origX = 0, origY = 0;

    function clamp(x, y){
      var w = el.offsetWidth, h = el.offsetHeight;
      var maxX = window.innerWidth - w - 6, maxY = window.innerHeight - h - 6;
      return { x: Math.max(6, Math.min(x, maxX)), y: Math.max(6, Math.min(y, maxY)) };
    }
    function place(x, y){
      var p = clamp(x, y);
      el.style.left = p.x + 'px'; el.style.top = p.y + 'px';
      el.style.right = 'auto'; el.style.bottom = 'auto';
      return p;
    }
    function restore(){
      try{
        var saved = JSON.parse(localStorage.getItem(POS_KEY) || 'null');
        if(saved && typeof saved.x === 'number') place(saved.x, saved.y);
      }catch(e){}
    }
    function start(x, y){
      dragging = true; moved = false;
      var r = el.getBoundingClientRect();
      startX = x; startY = y; origX = r.left; origY = r.top;
      el.classList.add('a11y-dragging');
      document.body.classList.add('a11y-no-select');
    }
    function move(x, y){
      if(!dragging) return;
      var dx = x - startX, dy = y - startY;
      if(Math.abs(dx) > 4 || Math.abs(dy) > 4) moved = true;
      if(moved) place(origX + dx, origY + dy);
    }
    function end(){
      if(!dragging) return;
      dragging = false;
      el.classList.remove('a11y-dragging');
      document.body.classList.remove('a11y-no-select');
      if(moved){
        var r = el.getBoundingClientRect();
        try{ localStorage.setItem(POS_KEY, JSON.stringify({x: r.left, y: r.top})); }catch(e){}
        if(onDragEnd) onDragEnd(true);
      } else if(onDragEnd) onDragEnd(false);
    }
    el.addEventListener('mousedown', function(e){ start(e.clientX, e.clientY); e.preventDefault(); });
    document.addEventListener('mousemove', function(e){ move(e.clientX, e.clientY); });
    document.addEventListener('mouseup', end);
    el.addEventListener('touchstart', function(e){ var t = e.touches[0]; start(t.clientX, t.clientY); }, {passive: true});
    document.addEventListener('touchmove', function(e){ if(dragging){ var t = e.touches[0]; move(t.clientX, t.clientY); e.preventDefault(); } }, {passive: false});
    document.addEventListener('touchend', end);
    window.addEventListener('resize', function(){
      var r = el.getBoundingClientRect();
      place(r.left, r.top);
    });
    restore();
  }

  /* Posiciona o painel encostado no botão, onde quer que ele esteja na tela ── */
  function positionPanel(btn, panel){
    var r = btn.getBoundingClientRect();
    var pw = panel.offsetWidth || 290, ph = panel.offsetHeight || 420;
    var spaceBelow = window.innerHeight - r.bottom, spaceAbove = r.top;
    var top = (spaceBelow > ph + 16 || spaceBelow > spaceAbove) ? r.bottom + 10 : r.top - ph - 10;
    top = Math.max(8, Math.min(top, window.innerHeight - ph - 8));
    var left = Math.max(8, Math.min(r.left, window.innerWidth - pw - 8));
    panel.style.left = left + 'px'; panel.style.top = top + 'px';
    panel.style.right = 'auto'; panel.style.bottom = 'auto';
  }

  /* ── Monta o painel ── */
  function buildUI(){
    var btn = document.createElement('button');
    btn.id = 'a11yBtn';
    btn.type = 'button';
    btn.setAttribute('aria-label', 'Abrir opções de acessibilidade');
    btn.setAttribute('aria-haspopup', 'dialog');
    btn.setAttribute('aria-expanded', 'false');
    btn.title = 'Toque e arraste para mover · clique para abrir';
    btn.innerHTML = '<i class="fa-solid fa-universal-access" aria-hidden="true"></i>';

    var panel = document.createElement('div');
    panel.id = 'a11yPanel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Opções de acessibilidade');
    panel.innerHTML =
      '<button type="button" class="a11y-close" aria-label="Fechar"><i class="fa-solid fa-xmark"></i></button>' +
      '<h2>Acessibilidade</h2>' +
      '<div class="a11y-sub">Ajuste a exibição do TaskAI ao que for mais confortável para você.</div>' +

      '<div class="a11y-row">' +
        '<div><div class="a11y-label">Tamanho da fonte</div><div class="a11y-desc">Aumenta o texto de toda a página</div></div>' +
        '<div class="a11y-fsbtns" role="group" aria-label="Tamanho da fonte">' +
          '<button type="button" data-fs="0" aria-label="Fonte padrão">A</button>' +
          '<button type="button" data-fs="1" aria-label="Fonte grande">A+</button>' +
          '<button type="button" data-fs="2" aria-label="Fonte maior">A++</button>' +
          '<button type="button" data-fs="3" aria-label="Fonte muito maior">A+++</button>' +
        '</div>' +
      '</div>' +

      '<div class="a11y-row">' +
        '<div><div class="a11y-label">Alto contraste</div><div class="a11y-desc">Preto e amarelo, para baixa visão</div></div>' +
        '<button type="button" class="a11y-switch" id="a11ySwContrast" role="switch" aria-checked="false" aria-label="Ativar alto contraste"><span class="knob"></span></button>' +
      '</div>' +

      '<div class="a11y-row">' +
        '<div><div class="a11y-label">Sublinhar links</div><div class="a11y-desc">Facilita identificar links no texto</div></div>' +
        '<button type="button" class="a11y-switch" id="a11ySwUnderline" role="switch" aria-checked="false" aria-label="Ativar sublinhado de links"><span class="knob"></span></button>' +
      '</div>' +

      '<div class="a11y-row">' +
        '<div><div class="a11y-label">Reduzir animações</div><div class="a11y-desc">Desativa transições e efeitos de movimento</div></div>' +
        '<button type="button" class="a11y-switch" id="a11ySwMotion" role="switch" aria-checked="false" aria-label="Ativar redução de animações"><span class="knob"></span></button>' +
      '</div>' +

      '<div class="a11y-row">' +
        '<div><div class="a11y-label">Tradução em Libras</div><div class="a11y-desc">Widget oficial do governo (VLibras) — também soletra siglas como "IA" quando não há sinal específico</div></div>' +
        '<button type="button" class="a11y-switch" id="a11ySwLibras" role="switch" aria-checked="false" aria-label="Ativar tradução em Libras"><span class="knob"></span></button>' +
      '</div>' +

      '<button type="button" class="a11y-readbtn" id="a11yReadBtn"><i class="fa-solid fa-volume-high"></i> Ler esta página em voz alta</button>' +
      '<button type="button" class="a11y-resetbtn" id="a11yReset">Restaurar padrão</button>';

    document.body.appendChild(btn);
    document.body.appendChild(panel);

    var suppressClick = false;
    makeDraggable(btn, function(wasDrag){
      if(wasDrag){ suppressClick = true; setTimeout(function(){ suppressClick = false; }, 60); }
    });

    function openPanel(){
      panel.classList.add('on');
      btn.setAttribute('aria-expanded', 'true');
      positionPanel(btn, panel);
      syncUI();
      var first = panel.querySelector('.a11y-close');
      if(first) first.focus();
    }
    function closePanel(){
      panel.classList.remove('on');
      btn.setAttribute('aria-expanded', 'false');
      btn.focus();
    }
    btn.addEventListener('click', function(){
      if(suppressClick) return;
      panel.classList.contains('on') ? closePanel() : openPanel();
    });
    /* API pública: usada pelo botão "Abrir painel de acessibilidade" em Configurações */
    var openedAt = 0;
    window.openA11yPanel = function(){
      if(!panel.classList.contains('on')){ openedAt = Date.now(); openPanel(); }
    };
    window.addEventListener('resize', function(){
      if(panel.classList.contains('on')) positionPanel(btn, panel);
    });
    panel.querySelector('.a11y-close').addEventListener('click', closePanel);
    document.addEventListener('keydown', function(e){
      if(e.key === 'Escape' && panel.classList.contains('on')) closePanel();
    });
    document.addEventListener('click', function(e){
      if(Date.now() - openedAt < 300) return; /* ignora o clique que acabou de abrir o painel */
      if(panel.classList.contains('on') && !e.target.closest('#a11yPanel') && !e.target.closest('#a11yBtn') && !e.target.closest('[data-open-a11y]')) closePanel();
    });

    panel.querySelectorAll('.a11y-fsbtns button').forEach(function(b){
      b.addEventListener('click', function(){
        prefs.fs = parseInt(b.dataset.fs, 10);
        savePrefs(prefs); applyPrefs(); syncUI();
      });
    });

    function wireSwitch(id, key){
      var el = document.getElementById(id);
      el.addEventListener('click', function(){
        prefs[key] = !prefs[key];
        savePrefs(prefs); applyPrefs(); syncUI();
      });
    }
    wireSwitch('a11ySwContrast', 'contrast');
    wireSwitch('a11ySwUnderline', 'underline');
    wireSwitch('a11ySwMotion', 'reduceMotion');
    wireSwitch('a11ySwLibras', 'libras');

    document.getElementById('a11yReadBtn').addEventListener('click', function(){
      toggleRead(this);
    });
    document.getElementById('a11yReset').addEventListener('click', function(){
      prefs = {fs:0, contrast:false, underline:false, reduceMotion:false, libras:false};
      savePrefs(prefs); applyPrefs(); syncUI();
      if(speaking && 'speechSynthesis' in window) window.speechSynthesis.cancel();
      speaking = false; setReadBtnState(document.getElementById('a11yReadBtn'), false);
    });

    function syncUI(){
      panel.querySelectorAll('.a11y-fsbtns button').forEach(function(b){
        b.classList.toggle('on', parseInt(b.dataset.fs,10) === prefs.fs);
      });
      document.getElementById('a11ySwContrast').setAttribute('aria-checked', String(!!prefs.contrast));
      document.getElementById('a11ySwUnderline').setAttribute('aria-checked', String(!!prefs.underline));
      document.getElementById('a11ySwMotion').setAttribute('aria-checked', String(!!prefs.reduceMotion));
      document.getElementById('a11ySwLibras').setAttribute('aria-checked', String(!!prefs.libras));
    }
    syncUI();
  }

  function init(){
    applyPrefs();
    buildUI();
  }
  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
