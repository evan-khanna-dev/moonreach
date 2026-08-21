// MoonReach 3D scene — ported from scene.html (Three.js r128).
//
// Phase-1 state: a faithful 1:1 port of scene.html's script. No panel logic,
// no raycasting/focus system yet (those land in later phases on top of this
// same file) — this file's job right now is just to render identically to
// scene.html, with the MR namespace/bus scaffold in place for what's next.
//
// scene.js owns the renderer + interaction only. It never reaches into panel
// DOM and never knows what a "profile" or "chat" is - app.js is the only
// thing that knows that, and talks to this file through window.MR.

window.MR = window.MR || {};
MR.bus = MR.bus || new EventTarget();

(function () {
  const stage = document.getElementById('stage');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.outputEncoding = THREE.sRGBEncoding;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.02;
  stage.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a1146);

  const camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 900);

  /* ---------- palette (sampled from the source painting) ---------- */
  const PAL = {
    skyTop:    '#0b1149',
    skyDeep:   '#141f68',
    skyHaze:   '#2a3486',
    wisp:      '#3b3f9a',
    moonLight: '#f4f8ff',
    moonMid:   '#d8e4fb',
    moonMare:  '#a9bee4',
    moonDeep:  '#8ba4d4',
    rockLight: '#a9b6d2',
    rockMid:   '#6c7b9f',
    rockDeep:  '#39466f',
    rockShade: '#222c52',
    gold:      '#e8c079',
    goldPale:  '#f6dfae',
    astLight:  '#5d6070',
    astMid:    '#3f424f',
    astDeep:   '#23252f',
    dust:      '#7b5fd4'
  };

  /* ---------- camera orbit state (drag and drift kept separate) ---------- */
  // target/tTarget generalize the old fixed (0,2,0) look-at into a movable
  // point so per-object focus presets can orbit the clicked object itself,
  // not just the origin - this is what every focus()/release() call below
  // hinges on. beltSpinScale slows the asteroid tumble during belt-chat
  // docking without touching the asteroids' own idle-motion constants.
  const orbit = {
    theta: 0, phi: 0, dist: 16, userTheta: 0, tUserTheta: 0, tPhi: 0, tDist: 16, driftTheta: 0,
    target: new THREE.Vector3(0, 2, 0), tTarget: new THREE.Vector3(0, 2, 0),
    beltSpinScale: 1, tBeltSpinScale: 1
  };
  function placeCamera() {
    const x = orbit.target.x + orbit.dist * Math.cos(orbit.phi) * Math.sin(orbit.theta);
    const y = orbit.target.y + orbit.dist * Math.sin(orbit.phi);
    const z = orbit.target.z + orbit.dist * Math.cos(orbit.phi) * Math.cos(orbit.theta);
    camera.position.set(x, y, z);
    camera.lookAt(orbit.target);
  }

  /* ---------- texture helpers ---------- */
  function canvasTexture(w, h, draw) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    draw(c.getContext('2d'), w, h);
    const t = new THREE.CanvasTexture(c);
    t.anisotropy = renderer.capabilities.getMaxAnisotropy();
    t.needsUpdate = true;
    return t;
  }
  const rand = (a, b) => a + Math.random() * (b - a);

  function grain(ctx, w, h, count, alpha, colors) {
    for (let i = 0; i < count; i++) {
      ctx.fillStyle = colors[(Math.random() * colors.length) | 0];
      ctx.globalAlpha = Math.random() * alpha;
      const s = Math.random() < 0.85 ? 1 : 2;
      ctx.fillRect(Math.random() * w, Math.random() * h, s, s);
    }
    ctx.globalAlpha = 1;
  }

  const dotTexture = canvasTexture(64, 64, (ctx, w) => {
    const g = ctx.createRadialGradient(w / 2, w / 2, 0, w / 2, w / 2, w / 2);
    g.addColorStop(0, 'rgba(255,255,255,1)');
    g.addColorStop(0.35, 'rgba(255,255,255,0.65)');
    g.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, w);
  });

  const glowTexture = canvasTexture(256, 256, (ctx, w) => {
    const g = ctx.createRadialGradient(w / 2, w / 2, w * 0.17, w / 2, w / 2, w / 2);
    g.addColorStop(0, 'rgba(216,234,255,0.9)');
    g.addColorStop(0.24, 'rgba(160,196,255,0.36)');
    g.addColorStop(0.55, 'rgba(96,136,240,0.13)');
    g.addColorStop(1, 'rgba(60,92,205,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, w);
  });

  const flareTexture = canvasTexture(256, 256, (ctx, w) => {
    const c = w / 2;
    const core = ctx.createRadialGradient(c, c, 0, c, c, w * 0.15);
    core.addColorStop(0, 'rgba(255,255,255,1)');
    core.addColorStop(0.45, 'rgba(206,228,255,0.55)');
    core.addColorStop(1, 'rgba(160,200,255,0)');
    ctx.fillStyle = core;
    ctx.fillRect(0, 0, w, w);
    for (let i = 0; i < 2; i++) {
      ctx.save();
      ctx.translate(c, c);
      ctx.rotate(i * Math.PI / 2);
      const g = ctx.createLinearGradient(-c, 0, c, 0);
      g.addColorStop(0, 'rgba(255,255,255,0)');
      g.addColorStop(0.5, 'rgba(255,255,255,0.95)');
      g.addColorStop(1, 'rgba(255,255,255,0)');
      ctx.fillStyle = g;
      const thick = i === 0 ? 4 : 2.2;
      ctx.beginPath();
      ctx.moveTo(-c, 0); ctx.lineTo(0, -thick); ctx.lineTo(c, 0); ctx.lineTo(0, thick);
      ctx.closePath(); ctx.fill();
      ctx.restore();
    }
  });

  /* ---------- sky dome ---------- */
  const skyTexture = canvasTexture(2048, 1024, (ctx, w, h) => {
    const g = ctx.createLinearGradient(0, 0, 0, h);
    g.addColorStop(0, PAL.skyTop);
    g.addColorStop(0.42, PAL.skyDeep);
    g.addColorStop(0.78, '#101a5c');
    g.addColorStop(1, '#080d38');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);

    // soft indigo cloud wisps, as in the upper-left of the painting
    for (let i = 0; i < 28; i++) {
      const x = rand(0, w), y = rand(h * 0.08, h * 0.85);
      const rx = rand(140, 460), ry = rand(40, 150);
      const rg = ctx.createRadialGradient(x, y, 0, x, y, rx);
      rg.addColorStop(0, i % 3 ? 'rgba(59,63,154,0.20)' : 'rgba(42,52,134,0.24)');
      rg.addColorStop(1, 'rgba(20,31,104,0)');
      ctx.fillStyle = rg;
      ctx.save();
      ctx.translate(x, y); ctx.rotate(rand(-0.6, 0.6)); ctx.scale(1, ry / rx);
      ctx.beginPath(); ctx.arc(0, 0, rx, 0, 6.29); ctx.fill();
      ctx.restore();
    }
    grain(ctx, w, h, 5200, 0.30, ['#7f8fd8', '#5a6ac0', '#9aa8ea']);
  });

  const skyDome = new THREE.Mesh(
    new THREE.SphereGeometry(420, 48, 32),
    new THREE.MeshBasicMaterial({ map: skyTexture, side: THREE.BackSide, depthWrite: false })
  );
  scene.add(skyDome);

  /* ---------- moon texture ---------- */
  const moonTexture = canvasTexture(2048, 1024, (ctx, w, h) => {
    const base = ctx.createLinearGradient(0, 0, 0, h);
    base.addColorStop(0, PAL.moonLight);
    base.addColorStop(0.45, PAL.moonMid);
    base.addColorStop(1, '#e7eefd');
    ctx.fillStyle = base;
    ctx.fillRect(0, 0, w, h);

    // maria: broad blue-grey plains with soft irregular edges
    for (let i = 0; i < 34; i++) {
      const x = rand(0, w), y = rand(70, h - 70), r = rand(70, 260);
      const g = ctx.createRadialGradient(x, y, r * 0.1, x, y, r);
      g.addColorStop(0, 'rgba(140,166,214,0.42)');
      g.addColorStop(0.6, 'rgba(158,182,224,0.24)');
      g.addColorStop(1, 'rgba(158,182,224,0)');
      ctx.fillStyle = g;
      ctx.save();
      ctx.translate(x, y); ctx.rotate(rand(0, 3.14));
      ctx.beginPath(); ctx.ellipse(0, 0, r, r * rand(0.55, 0.85), 0, 0, 6.29); ctx.fill();
      ctx.restore();
    }

    // ray system radiating from the southern highland crater
    const rx = w * 0.63, ry = h * 0.74;
    ctx.save();
    for (let i = 0; i < 60; i++) {
      const a = rand(0, 6.29), len = rand(120, 430);
      const g = ctx.createLinearGradient(rx, ry, rx + Math.cos(a) * len, ry + Math.sin(a) * len);
      g.addColorStop(0, 'rgba(255,255,255,0.85)');
      g.addColorStop(0.35, 'rgba(255,255,255,0.45)');
      g.addColorStop(1, 'rgba(255,255,255,0)');
      ctx.strokeStyle = g;
      ctx.lineWidth = rand(1.5, 7);
      ctx.beginPath(); ctx.moveTo(rx, ry);
      ctx.lineTo(rx + Math.cos(a) * len, ry + Math.sin(a) * len);
      ctx.stroke();
    }
    ctx.restore();

    // craters: rim, floor, shadow arc, central peak on the large ones
    function crater(x, y, r) {
      const floor = ctx.createRadialGradient(x, y, r * 0.1, x, y, r);
      floor.addColorStop(0, 'rgba(136,162,212,0.55)');
      floor.addColorStop(0.75, 'rgba(160,182,222,0.38)');
      floor.addColorStop(1, 'rgba(180,200,232,0.10)');
      ctx.fillStyle = floor;
      ctx.beginPath(); ctx.arc(x, y, r, 0, 6.29); ctx.fill();

      ctx.strokeStyle = 'rgba(255,255,255,0.92)';
      ctx.lineWidth = Math.max(1, r * 0.14);
      ctx.beginPath(); ctx.arc(x, y, r * 0.95, 0, 6.29); ctx.stroke();

      ctx.strokeStyle = 'rgba(120,146,200,0.55)';
      ctx.lineWidth = Math.max(1, r * 0.18);
      ctx.beginPath(); ctx.arc(x, y, r * 0.72, 2.2, 5.2); ctx.stroke();

      ctx.fillStyle = 'rgba(255,255,255,0.40)';
      ctx.beginPath(); ctx.arc(x - r * 0.2, y - r * 0.22, r * 0.4, 0, 6.29); ctx.fill();

      if (r > 26) {
        ctx.fillStyle = 'rgba(246,250,255,0.75)';
        ctx.beginPath(); ctx.arc(x, y, r * 0.13, 0, 6.29); ctx.fill();
      }
    }
    for (let i = 0; i < 90; i++) crater(rand(0, w), rand(30, h - 30), rand(16, 58));
    for (let i = 0; i < 320; i++) crater(rand(0, w), rand(20, h - 20), rand(4, 15));
    for (let i = 0; i < 900; i++) {
      ctx.fillStyle = 'rgba(150,175,222,0.5)';
      ctx.globalAlpha = Math.random() * 0.6;
      const r = rand(1, 3.5);
      ctx.beginPath(); ctx.arc(rand(0, w), rand(0, h), r, 0, 6.29); ctx.fill();
    }
    ctx.globalAlpha = 1;
    grain(ctx, w, h, 9000, 0.16, ['#ffffff', '#b9cbee', '#8ba4d4']);
  });

  /* ---------- rock texture for the ridge ---------- */
  const rockTexture = canvasTexture(1024, 1024, (ctx, w, h) => {
    const g = ctx.createLinearGradient(0, h, 0, 0);
    g.addColorStop(0, PAL.rockShade);
    g.addColorStop(0.42, PAL.rockDeep);
    g.addColorStop(0.78, PAL.rockMid);
    g.addColorStop(1, PAL.rockLight);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);

    // strata: long diagonal bands of slightly different slate
    for (let i = 0; i < 90; i++) {
      const y = rand(0, h);
      ctx.strokeStyle = i % 2 ? 'rgba(169,182,210,0.16)' : 'rgba(34,44,82,0.22)';
      ctx.lineWidth = rand(2, 16);
      ctx.beginPath();
      ctx.moveTo(-20, y);
      ctx.bezierCurveTo(w * 0.3, y + rand(-40, 40), w * 0.7, y + rand(-40, 40), w + 20, y + rand(-30, 30));
      ctx.stroke();
    }

    // fracture lines
    for (let i = 0; i < 150; i++) {
      let x = rand(0, w), y = rand(0, h);
      ctx.strokeStyle = 'rgba(20,27,54,0.55)';
      ctx.lineWidth = rand(0.8, 2.6);
      ctx.beginPath(); ctx.moveTo(x, y);
      for (let s = 0; s < 5; s++) {
        x += rand(-70, 70); y += rand(-50, 50);
        ctx.lineTo(x, y);
      }
      ctx.stroke();
    }

    // lit facet chips catching the moonlight
    for (let i = 0; i < 260; i++) {
      const x = rand(0, w), y = rand(0, h);
      ctx.fillStyle = Math.random() < 0.35 ? 'rgba(246,223,174,0.20)' : 'rgba(190,204,232,0.20)';
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(x + rand(6, 34), y + rand(-14, 14));
      ctx.lineTo(x + rand(-10, 24), y + rand(10, 40));
      ctx.closePath(); ctx.fill();
    }

    // sparse gold mineral flecks
    for (let i = 0; i < 220; i++) {
      ctx.fillStyle = Math.random() < 0.5 ? PAL.gold : PAL.goldPale;
      ctx.globalAlpha = rand(0.25, 0.8);
      ctx.beginPath(); ctx.arc(rand(0, w), rand(0, h), rand(0.8, 2.4), 0, 6.29); ctx.fill();
    }
    ctx.globalAlpha = 1;
    grain(ctx, w, h, 14000, 0.22, ['#a9b6d2', '#222c52', '#6c7b9f']);
  });
  rockTexture.wrapS = rockTexture.wrapT = THREE.RepeatWrapping;
  rockTexture.repeat.set(3, 2);

  /* ---------- asteroid regolith texture ---------- */
  const astTexture = canvasTexture(512, 512, (ctx, w, h) => {
    ctx.fillStyle = PAL.astMid;
    ctx.fillRect(0, 0, w, h);
    for (let i = 0; i < 60; i++) {
      const x = rand(0, w), y = rand(0, h), r = rand(20, 90);
      const g = ctx.createRadialGradient(x, y, 0, x, y, r);
      g.addColorStop(0, 'rgba(93,96,112,0.5)');
      g.addColorStop(1, 'rgba(93,96,112,0)');
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(x, y, r, 0, 6.29); ctx.fill();
    }
    for (let i = 0; i < 240; i++) {
      const x = rand(0, w), y = rand(0, h), r = rand(3, 22);
      ctx.fillStyle = 'rgba(24,26,34,0.75)';
      ctx.beginPath(); ctx.arc(x, y, r, 0, 6.29); ctx.fill();
      ctx.strokeStyle = 'rgba(126,130,148,0.5)';
      ctx.lineWidth = Math.max(0.8, r * 0.16);
      ctx.beginPath(); ctx.arc(x, y, r * 0.95, 3.5, 6.1); ctx.stroke();
    }
    grain(ctx, w, h, 9000, 0.35, ['#5d6070', '#23252f', '#7c8092']);
  });
  astTexture.wrapS = astTexture.wrapT = THREE.RepeatWrapping;

  /* ---------- nebula ---------- */
  const nebulaTexture = canvasTexture(1024, 1024, (ctx, w) => {
    ctx.clearRect(0, 0, w, w);
    const blobs = [
      ['rgba(123,95,212,0.30)', 0.30, 0.34, 0.40],
      ['rgba(72,112,238,0.26)', 0.60, 0.54, 0.38],
      ['rgba(178,124,236,0.22)', 0.46, 0.70, 0.28],
      ['rgba(92,152,255,0.18)', 0.74, 0.28, 0.26],
      ['rgba(215,168,255,0.12)', 0.38, 0.52, 0.18]
    ];
    blobs.forEach(([col, cx, cy, r]) => {
      const g = ctx.createRadialGradient(cx * w, cy * w, 0, cx * w, cy * w, r * w);
      g.addColorStop(0, col);
      g.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, w, w);
    });
    // dust lanes carved through the band
    ctx.globalCompositeOperation = 'destination-out';
    for (let i = 0; i < 22; i++) {
      const y = rand(0, w);
      ctx.strokeStyle = 'rgba(0,0,0,0.5)';
      ctx.lineWidth = rand(6, 40);
      ctx.beginPath();
      ctx.moveTo(-10, y);
      ctx.bezierCurveTo(w * 0.35, y + rand(-90, 90), w * 0.7, y + rand(-90, 90), w + 10, y + rand(-60, 60));
      ctx.stroke();
    }
    ctx.globalCompositeOperation = 'source-over';
    for (let i = 0; i < 9000; i++) {
      const x = Math.random() * w, y = Math.random() * w;
      ctx.fillStyle = `rgba(255,255,255,${Math.random() * 0.55})`;
      ctx.fillRect(x, y, Math.random() < 0.92 ? 1 : 2, 1);
    }
  });

  /* ---------- star fields ---------- */
  function starField(count, radiusMin, radiusMax, size, palette, band) {
    const pos = new Float32Array(count * 3);
    const col = new Float32Array(count * 3);
    const c = new THREE.Color();
    for (let i = 0; i < count; i++) {
      let v;
      if (band) {
        const u = Math.random() * Math.PI * 2;
        const spread = (Math.random() + Math.random() + Math.random() - 1.5) * 0.34;
        v = new THREE.Vector3(Math.cos(u), spread, Math.sin(u)).normalize();
        v.applyAxisAngle(new THREE.Vector3(0, 0, 1), -0.75);
        v.applyAxisAngle(new THREE.Vector3(1, 0, 0), 0.35);
      } else {
        const t = Math.random() * Math.PI * 2, p = Math.acos(2 * Math.random() - 1);
        v = new THREE.Vector3(Math.sin(p) * Math.cos(t), Math.cos(p), Math.sin(p) * Math.sin(t));
      }
      const r = radiusMin + Math.random() * (radiusMax - radiusMin);
      pos[i * 3] = v.x * r; pos[i * 3 + 1] = v.y * r; pos[i * 3 + 2] = v.z * r;
      c.set(palette[(Math.random() * palette.length) | 0]);
      col[i * 3] = c.r; col[i * 3 + 1] = c.g; col[i * 3 + 2] = c.b;
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('color', new THREE.BufferAttribute(col, 3));
    const m = new THREE.PointsMaterial({
      size, map: dotTexture, vertexColors: true, transparent: true,
      depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true
    });
    return new THREE.Points(g, m);
  }

  const sky = new THREE.Group();
  scene.add(sky);
  sky.add(starField(3200, 110, 190, 0.8, [0xffffff, 0xdfe8ff, 0xc9d6ff, 0xb9cbf7], false));
  const brightStars = starField(190, 110, 175, 2.1, [0xffffff, 0xeaf1ff, 0xf6dfae], false);
  sky.add(brightStars);
  sky.add(starField(2600, 120, 185, 0.95, [0xa98cff, 0x7f9dff, 0xd6b8ff, 0xffffff], true));

  const nebula = new THREE.Mesh(
    new THREE.PlaneGeometry(360, 360),
    new THREE.MeshBasicMaterial({
      map: nebulaTexture, transparent: true, opacity: 0.92,
      blending: THREE.AdditiveBlending, depthWrite: false
    })
  );
  nebula.position.set(44, -12, -178);
  nebula.rotation.z = -0.62;
  sky.add(nebula);

  /* ---------- moon ---------- */
  const moonR = 3.6;
  const moon = new THREE.Mesh(
    new THREE.SphereGeometry(moonR, 128, 128),
    new THREE.MeshStandardMaterial({
      map: moonTexture,
      emissiveMap: moonTexture,
      emissive: 0xdce8ff,
      emissiveIntensity: 0.46,
      bumpMap: moonTexture,
      bumpScale: 0.055,
      roughness: 1,
      metalness: 0
    })
  );
  moon.position.set(8.4, 6.2, -14);
  moon.rotation.y = -0.7;
  scene.add(moon);

  const moonGlow = new THREE.Sprite(new THREE.SpriteMaterial({
    map: glowTexture, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending
  }));
  moonGlow.scale.setScalar(moonR * 4.6);
  moonGlow.position.copy(moon.position);
  scene.add(moonGlow);

  // Invisible low-poly hit proxy for the moon - the real mesh is 128x128
  // (~32k tris), too expensive to raycast every hover frame. moonGlow is
  // deliberately never added to any pickables list, which is what "click
  // target: the moon mesh, not the glow sprite" means in practice.
  const moonProxy = new THREE.Mesh(
    new THREE.SphereGeometry(moonR, 16, 16),
    new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false })
  );
  moonProxy.position.copy(moon.position);
  moonProxy.userData.hitName = 'moon';
  scene.add(moonProxy);

  const flare = new THREE.Sprite(new THREE.SpriteMaterial({
    map: flareTexture, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending
  }));
  flare.scale.setScalar(7);
  flare.position.set(1.4, 9.2, -16);
  flare.userData.hitName = 'star';
  scene.add(flare);

  /* ---------- recommended-prompt stars ----------
     A small dedicated Points object holding just the CURRENT highlighted
     subset - copied positions from brightStars, never a reference into it,
     and never the full field. Raycasting only ever tests these few points,
     never the thousands in the background starfields. */
  const RECOMMENDED_COUNT = 5;
  let recommendedStars = null;
  let recommendedFadeIn = null;
  let recommendedFadeOut = null;

  function nearestBrightStarIndices(count, excludeSet) {
    const posAttr = brightStars.geometry.attributes.position;
    const candidates = [];
    for (let i = 0; i < posAttr.count; i++) {
      if (excludeSet && excludeSet.has(i)) continue;
      const dx = posAttr.getX(i) - flare.position.x;
      const dy = posAttr.getY(i) - flare.position.y;
      const dz = posAttr.getZ(i) - flare.position.z;
      candidates.push({ i, d: dx * dx + dy * dy + dz * dz });
    }
    candidates.sort((a, b) => a.d - b.d);
    return candidates.slice(0, count).map((c) => c.i);
  }

  function buildRecommendedStars(indices, promptIds) {
    const posAttr = brightStars.geometry.attributes.position;
    const pos = new Float32Array(indices.length * 3);
    indices.forEach((idx, k) => {
      pos[k * 3] = posAttr.getX(idx);
      pos[k * 3 + 1] = posAttr.getY(idx);
      pos[k * 3 + 2] = posAttr.getZ(idx);
    });
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    const m = new THREE.PointsMaterial({
      size: 4.4, map: dotTexture, color: 0xffd699, transparent: true,
      opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true
    });
    const points = new THREE.Points(g, m);
    points.userData.hitName = 'promptstar';
    points.userData.fadeT = 0; // eased 0..1 in tick, drives opacity/size
    points.userData.fadeTarget = 1;
    // Meta lives on the points object itself (not a shared array) so a click
    // during a crossfade always resolves against the buffer it actually hit,
    // even if an old and a new subset are both still on screen at once.
    points.userData.meta = promptIds.map((id) => ({ promptId: id }));
    scene.add(points);
    return points;
  }

  function reshuffleRecommendedStars(promptIds) {
    const prevIndices = recommendedStars ? recommendedStars.userData.sourceIndices : [];
    const exclude = new Set(prevIndices);
    const indices = nearestBrightStarIndices(RECOMMENDED_COUNT, exclude);
    const ids = (promptIds && promptIds.length ? promptIds : indices.map((_, i) => i)).slice(0, indices.length);
    const points = buildRecommendedStars(indices, ids);
    points.userData.sourceIndices = indices;

    if (recommendedStars) {
      recommendedFadeOut = recommendedStars;
      recommendedFadeOut.userData.fadeTarget = 0;
    }
    recommendedStars = points;
    recommendedFadeIn = points;
  }

  // Initial static subset (Phase 2: no reshuffle wiring yet, just the
  // pulsing/raycastable subset existing and being individually clickable).
  reshuffleRecommendedStars([]);

  /* ---------- lighting ---------- */
  scene.add(new THREE.AmbientLight(0x2b3c88, 0.8));
  scene.add(new THREE.HemisphereLight(0x8fa6ff, 0x141d4e, 0.45));
  const moonKey = new THREE.DirectionalLight(0xf6dcae, 1.3);
  moonKey.position.set(9, 8, -6);
  scene.add(moonKey);
  const coolFill = new THREE.DirectionalLight(0x6a86e8, 0.7);
  coolFill.position.set(-9, 4, 6);
  scene.add(coolFill);
  const faceLight = new THREE.DirectionalLight(0xcfe0ff, 0.42);
  faceLight.position.set(2, 3, 14);
  scene.add(faceLight);

  /* ---------- asteroids ---------- */
  function lump(x, y, z) {
    return 0.15 * Math.sin(3.1 * x + 1.2) * Math.cos(2.7 * y) +
           0.12 * Math.sin(2.3 * y + 0.4) * Math.cos(3.5 * z) +
           0.10 * Math.sin(4.1 * z + 2.1) * Math.cos(2.2 * x) +
           0.06 * Math.sin(6.7 * x + 3.3) * Math.sin(5.9 * y) +
           0.03 * Math.sin(11.3 * z + 0.7) * Math.cos(9.7 * x);
  }

  const astLight = new THREE.Color(PAL.astLight);
  const astMid = new THREE.Color(PAL.astMid);
  const astDeep = new THREE.Color(PAL.astDeep);

  function makeAsteroid(radius, seed) {
    const geo = new THREE.IcosahedronGeometry(radius, 4);
    const p = geo.attributes.position;
    const colors = new Float32Array(p.count * 3);
    const craters = [];
    for (let i = 0; i < 11; i++) {
      const a = seed * 12.9 + i * 2.399, b = seed * 7.7 + i * 1.117;
      craters.push({
        dir: new THREE.Vector3(Math.cos(a) * Math.sin(b), Math.cos(b), Math.sin(a) * Math.sin(b)).normalize(),
        size: 0.2 + ((i * 0.137 + seed * 0.31) % 1) * 0.32,
        depth: 0.08 + ((i * 0.29 + seed * 0.53) % 1) * 0.15
      });
    }
    const v = new THREE.Vector3(), c = new THREE.Color();
    for (let i = 0; i < p.count; i++) {
      v.fromBufferAttribute(p, i);
      const n = v.clone().normalize();
      let scale = 1 + lump(v.x + seed, v.y - seed, v.z + seed * 0.5);
      let dent = 0;
      for (const cr of craters) {
        const d = n.angleTo(cr.dir);
        if (d < cr.size) {
          const f = Math.cos((d / cr.size) * Math.PI * 0.5);
          scale -= cr.depth * f * f;
          dent = Math.max(dent, f * f);
        }
      }
      v.copy(n).multiplyScalar(radius * scale);
      p.setXYZ(i, v.x, v.y, v.z);

      // vertex colour: crater floors sink dark, high ridges catch grey
      const high = THREE.MathUtils.clamp((scale - 0.95) * 3.2, 0, 1);
      c.copy(astMid).lerp(astLight, high * 0.7).lerp(astDeep, dent * 0.85);
      colors[i * 3] = c.r; colors[i * 3 + 1] = c.g; colors[i * 3 + 2] = c.b;
    }
    geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    geo.computeVertexNormals();

    const mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
      map: astTexture,
      bumpMap: astTexture,
      bumpScale: 0.02,
      vertexColors: true,
      roughness: 0.97,
      metalness: 0.04,
      flatShading: true,
      emissive: 0x000000,
      emissiveIntensity: 0
    }));

    // painted-illustration outline, matching the source art
    const outline = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({
      color: 0x11131f, side: THREE.BackSide
    }));
    outline.scale.setScalar(1.045);
    mesh.add(outline);

    mesh.rotation.set(seed, seed * 1.7, seed * 0.6);
    return mesh;
  }

  const asteroids = [];
  [
    [-7.6, 5.9, -2.5, 0.62, 1.3],
    [-5.9, 4.3, 1.5, 0.95, 2.7],
    [-4.2, 2.9, -3.2, 0.52, 4.1],
    [0.9, -0.4, 2.4, 1.0, 5.9]
  ].forEach(([x, y, z, r, seed]) => {
    const a = makeAsteroid(r, seed);
    a.position.set(x, y, z);
    a.userData.spin = new THREE.Vector3(
      (Math.sin(seed) * 0.5 + 0.5) * 0.018 + 0.006,
      (Math.cos(seed) * 0.5 + 0.5) * 0.022 + 0.005,
      (Math.sin(seed * 2) * 0.5 + 0.5) * 0.012 + 0.004
    );
    a.userData.home = a.position.clone();
    a.userData.phase = seed;
    a.userData.radius = r;
    scene.add(a);
    asteroids.push(a);
  });

  // beltCentroid is still the belt's camera-target (FOCUS_PRESETS below), but
  // the click target is now a small proxy per asteroid rather than one sphere
  // spanning the whole cluster: a single bounding sphere has to stretch to
  // reach the farthest outlier rock, and that oversized volume ends up
  // swallowing raycasts meant for other objects (e.g. the star) that sit
  // behind or near it from plenty of camera angles. Each proxy tracks its
  // own asteroid's per-frame bob so hit-testing stays accurate without
  // touching the asteroids' visuals or spin.
  const beltCentroid = asteroids.reduce((acc, a) => acc.add(a.userData.home), new THREE.Vector3()).divideScalar(asteroids.length);
  const beltProxies = asteroids.map((a) => {
    const proxy = new THREE.Mesh(
      new THREE.SphereGeometry(a.userData.radius + 0.35, 10, 10),
      new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false })
    );
    proxy.position.copy(a.position);
    proxy.userData.hitName = 'belt';
    scene.add(proxy);
    return proxy;
  });

  /* ---------- ridge ---------- */
  const ridgeGeo = new THREE.ConeGeometry(10, 15, 34, 30);
  (function carve() {
    const p = ridgeGeo.attributes.position;
    const v = new THREE.Vector3();
    for (let i = 0; i < p.count; i++) {
      v.fromBufferAttribute(p, i);
      const r = Math.hypot(v.x, v.z);
      if (r < 0.001) continue;
      const th = Math.atan2(v.z, v.x);
      const ridges =
        0.20 * Math.sin(7 * th) +
        0.11 * Math.sin(13 * th + 1.7) +
        0.09 * Math.sin(5 * th + v.y * 0.45) +
        0.06 * Math.sin(21 * th + v.y * 0.9) +
        0.03 * Math.sin(33 * th + v.y * 1.6);
      const k = 1 + ridges * (0.55 + 0.45 * (r / 10));
      v.x *= k; v.z *= k;
      v.y += 0.55 * Math.sin(4 * th + r * 0.7) * (r / 10) + 0.18 * Math.sin(11 * th + r * 1.3);
      p.setXYZ(i, v.x, v.y, v.z);
    }
    ridgeGeo.computeVertexNormals();
  })();

  const ridge = new THREE.Mesh(ridgeGeo, new THREE.MeshStandardMaterial({
    map: rockTexture,
    bumpMap: rockTexture,
    bumpScale: 0.06,
    color: 0xc8d2ea,
    emissive: 0x101a44,
    emissiveIntensity: 0.35,
    roughness: 0.93,
    metalness: 0.05,
    flatShading: true
  }));
  ridge.position.set(-4.6, -4.6, 2);
  ridge.rotation.y = 0.4;
  ridge.userData.hitName = 'ridge';
  scene.add(ridge);

  (function flecks() {
    const src = ridgeGeo.attributes.position;
    const pts = [];
    for (let i = 0; i < src.count; i += 19) {
      const y = src.getY(i);
      if (y < -1.5 || Math.random() > 0.5) continue;
      pts.push(src.getX(i) * 1.005, y * 1.005, src.getZ(i) * 1.005);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(pts), 3));
    const m = new THREE.PointsMaterial({
      color: 0xf3cd86, size: 0.11, map: dotTexture, transparent: true,
      opacity: 0.8, depthWrite: false, blending: THREE.AdditiveBlending
    });
    const p = new THREE.Points(g, m);
    p.position.copy(ridge.position);
    p.rotation.copy(ridge.rotation);
    scene.add(p);
  })();

  /* ---------- focus presets & camera stack ----------
     One frame per focus() call, popped by release(). Single-level for
     ridge/moon/star (open -> close returns straight to whatever camera
     state existed before, including mid-drift, since driftTheta itself is
     never touched - only its target is suppressed while locked). Two-level
     for the belt: focus('belt') then focus('belt-chat') pushes two frames,
     so closing a chat pops back to the belt view (not the default scene),
     and closing the belt list pops back to default. */
  const FOCUS_PRESETS = {
    ridge:      { theta: 0.1,  phi: -0.15, dist: 7,   target: new THREE.Vector3(-4.6, 0, 6) },
    moon:       { theta: 0.25, phi: 0.06,  dist: 9,   target: moon.position.clone() },
    belt:       { theta: 0.15, phi: 0.08,  dist: 7.5, target: beltCentroid.clone() },
    'belt-chat':{ theta: 0.15, phi: 0.05,  dist: 4,   target: beltCentroid.clone() },
    star:       { theta: 0.2,  phi: 0.05,  dist: 6,   target: flare.position.clone() }
  };

  const focusStack = [];
  let drift = !reduceMotion;

  function focus(name) {
    const preset = FOCUS_PRESETS[name];
    if (!preset) return;
    focusStack.push({
      tUserTheta: orbit.tUserTheta, tPhi: orbit.tPhi, tDist: orbit.tDist,
      tTarget: orbit.tTarget.clone(), driftWasOn: drift
    });
    drift = false;
    orbit.tUserTheta = preset.theta;
    orbit.tPhi = preset.phi;
    orbit.tDist = preset.dist;
    orbit.tTarget.copy(preset.target);
    orbit.tBeltSpinScale = name === 'belt-chat' ? 0.15 : 1;
  }

  function release() {
    const frame = focusStack.pop();
    if (!frame) return;
    orbit.tUserTheta = frame.tUserTheta;
    orbit.tPhi = frame.tPhi;
    orbit.tDist = frame.tDist;
    orbit.tTarget.copy(frame.tTarget);
    drift = frame.driftWasOn;
    orbit.tBeltSpinScale = 1; // any release() leaves belt-chat's slowed tumble - restore full speed
  }

  function isLocked() { return focusStack.length > 0; }

  /* ---------- star mode tween (North Star vs Action Plan) ----------
     A tint/scale multiplier layered on TOP of the flare's existing idle
     pulse (never removed/replaced) - satisfies "shader/material property
     tween on the existing sprite, not a new object." */
  const STAR_MODE_COLORS = {
    northstar:  new THREE.Color(0xdfe9ff),
    actionplan: new THREE.Color(0xffcf8a)
  };
  const flareState = {
    mode: 'northstar',
    color: STAR_MODE_COLORS.northstar.clone(),
    tColor: STAR_MODE_COLORS.northstar.clone(),
    scaleMul: 1, tScaleMul: 1
  };
  function setStarMode(mode) {
    if (!STAR_MODE_COLORS[mode]) return;
    flareState.mode = mode;
    flareState.tColor.copy(STAR_MODE_COLORS[mode]);
    flareState.tScaleMul = mode === 'actionplan' ? 1.15 : 1;
  }

  /* ---------- pickables & raycasting ---------- */
  const raycaster = new THREE.Raycaster();
  raycaster.params.Points.threshold = 0.8;
  const pointer2 = new THREE.Vector2();

  function getPickables() {
    // recommendedStars is the CURRENT subset and must always stay pickable,
    // not just while recommendedFadeIn is still easing toward full opacity -
    // it's the only reference once a fade-in completes. recommendedFadeOut
    // is included too so a still-visible outgoing subset stays clickable
    // for the length of its own fade during a reshuffle crossfade.
    const list = [ridge, moonProxy, flare, ...beltProxies];
    if (recommendedStars) list.push(recommendedStars);
    if (recommendedFadeOut && recommendedFadeOut !== recommendedStars) list.push(recommendedFadeOut);
    return list;
  }

  function raycastAt(clientX, clientY) {
    const rect = el.getBoundingClientRect();
    pointer2.x = ((clientX - rect.left) / Math.max(rect.width, 1)) * 2 - 1;
    pointer2.y = -(((clientY - rect.top) / Math.max(rect.height, 1)) * 2 - 1);
    raycaster.setFromCamera(pointer2, camera);
    const hits = raycaster.intersectObjects(getPickables(), false);
    return hits.length ? hits[0] : null;
  }

  let hoveredName = null;
  const hoverT = { ridge: 0, moon: 0, belt: 0, star: 0 };

  function applyHover(hit) {
    const name = hit ? hit.object.userData.hitName : null;
    hoveredName = name === 'promptstar' ? 'promptstar' : name;
    el.style.cursor = hoveredName ? 'pointer' : '';
  }

  /* ---------- interaction ---------- */
  let dragging = false, lastX = 0, lastY = 0;
  let downX = 0, downY = 0, downTime = 0;
  let pendingHoverCheck = false;
  let lastPointerX = 0, lastPointerY = 0;
  const el = renderer.domElement;

  el.addEventListener('pointerdown', (e) => {
    downX = e.clientX; downY = e.clientY; downTime = performance.now();
    if (isLocked()) return; // locked while a panel's camera shot is held - no free orbiting
    dragging = true; lastX = e.clientX; lastY = e.clientY;
    el.setPointerCapture(e.pointerId);
  });
  el.addEventListener('pointermove', (e) => {
    lastPointerX = e.clientX; lastPointerY = e.clientY;
    if (!dragging) { pendingHoverCheck = true; return; }
    orbit.tUserTheta -= (e.clientX - lastX) * 0.0038;
    orbit.tPhi = THREE.MathUtils.clamp(orbit.tPhi + (e.clientY - lastY) * 0.0022, -0.32, 0.55);
    lastX = e.clientX; lastY = e.clientY;
  });
  el.addEventListener('pointerup', (e) => {
    dragging = false;
    const moved = Math.hypot(e.clientX - downX, e.clientY - downY);
    const elapsed = performance.now() - downTime;
    const threshold = e.pointerType === 'touch' ? 10 : 6;
    if (moved < threshold && elapsed < 350 && !isLocked()) {
      const hit = raycastAt(e.clientX, e.clientY);
      if (hit) {
        const name = hit.object.userData.hitName;
        if (name === 'promptstar') {
          const idx = hit.index != null ? hit.index : 0;
          const meta = (hit.object.userData.meta || [])[idx];
          MR.bus.dispatchEvent(new CustomEvent('starprompt:click', { detail: meta || {} }));
        } else {
          MR.bus.dispatchEvent(new CustomEvent('object:click', { detail: { name } }));
        }
      }
    }
  });
  el.addEventListener('pointercancel', () => { dragging = false; });
  el.addEventListener('wheel', (e) => {
    e.preventDefault();
    if (isLocked()) return;
    orbit.tDist = THREE.MathUtils.clamp(orbit.tDist + e.deltaY * 0.012, 8, 34);
  }, { passive: false });

  const driftBtn = document.getElementById('drift');
  driftBtn.setAttribute('aria-pressed', String(drift));
  driftBtn.addEventListener('click', () => {
    drift = !drift;
    driftBtn.setAttribute('aria-pressed', String(drift));
  });
  document.getElementById('reset').addEventListener('click', () => {
    orbit.tUserTheta = 0; orbit.tPhi = 0; orbit.tDist = 16;
  });

  /* ---------- loop ---------- */
  const clock = new THREE.Clock();
  const EASE = 0.06;
  function tick() {
    requestAnimationFrame(tick);
    const t = clock.getElapsedTime();
    const dt = Math.min(clock.getDelta(), 0.05);

    // drift is an offset layered on top of your heading, never a replacement for it
    const driftTarget = drift && !dragging ? Math.sin(t * 0.05) * 0.16 : 0;
    orbit.driftTheta += (driftTarget - orbit.driftTheta) * 0.02;
    orbit.userTheta += (orbit.tUserTheta - orbit.userTheta) * 0.09;
    orbit.theta = orbit.userTheta + orbit.driftTheta;
    orbit.phi += (orbit.tPhi - orbit.phi) * EASE;
    orbit.dist += (orbit.tDist - orbit.dist) * EASE;
    orbit.target.lerp(orbit.tTarget, EASE);
    orbit.beltSpinScale += (orbit.tBeltSpinScale - orbit.beltSpinScale) * EASE;
    placeCamera();

    asteroids.forEach((a, i) => {
      a.rotation.x += a.userData.spin.x * dt * orbit.beltSpinScale;
      a.rotation.y += a.userData.spin.y * dt * orbit.beltSpinScale;
      a.rotation.z += a.userData.spin.z * dt * orbit.beltSpinScale;
      const h = a.userData.home, ph = a.userData.phase;
      a.position.set(
        h.x + Math.sin(t * 0.14 + ph) * 0.05,
        h.y + Math.sin(t * 0.11 + ph * 1.6) * 0.07,
        h.z + Math.cos(t * 0.09 + ph) * 0.04
      );
      beltProxies[i].position.copy(a.position);
    });

    moon.rotation.y += 0.004 * dt;
    sky.rotation.y += 0.0016 * dt;
    brightStars.material.opacity = 0.72 + Math.sin(t * 0.9) * 0.16;

    // Flare: idle pulse (untouched base behavior) combined with the
    // hover/mode multipliers layered on top, and a tint tween toward
    // whichever star-mode is active.
    flareState.scaleMul += (flareState.tScaleMul - flareState.scaleMul) * EASE;
    flareState.color.lerp(flareState.tColor, EASE);
    flare.material.color.copy(flareState.color);
    const hoverScaleMul = 1 + hoverT.star * 0.15;
    flare.scale.setScalar((7 + Math.sin(t * 1.4) * 0.35) * flareState.scaleMul * hoverScaleMul);

    // Hover: raycast at most once per rendered frame, never per raw
    // pointermove event (which can fire 100+/s) - see pendingHoverCheck.
    if (pendingHoverCheck && !dragging) {
      pendingHoverCheck = false;
      const hit = isLocked() ? null : raycastAt(lastPointerX, lastPointerY);
      applyHover(hit);
    }
    ['ridge', 'moon', 'belt', 'star'].forEach((key) => {
      const on = hoveredName === key ? 1 : 0;
      hoverT[key] += (on - hoverT[key]) * 0.15;
    });
    ridge.material.emissiveIntensity = 0.35 + hoverT.ridge * 0.35;
    moon.material.emissiveIntensity = 0.46 + hoverT.moon * 0.22;
    asteroids.forEach((a) => {
      a.material.emissive.setHex(0xf0c274);
      a.material.emissiveIntensity = hoverT.belt * 0.5;
    });

    // Recommended-prompt stars: crossfade opacity/size, sine pulse on top,
    // plus a small hover boost (affordance requirement covers these too,
    // not just the 4 main objects) - can't glow a single point in a shared
    // Points object cheaply, so hovering any of them boosts the whole group.
    const promptHoverBoost = hoveredName === 'promptstar' ? 1.25 : 1;
    const pulse = (0.82 + Math.sin(t * 1.6) * 0.18) * promptHoverBoost;
    if (recommendedFadeIn) {
      const o = recommendedFadeIn.userData;
      o.fadeT += (o.fadeTarget - o.fadeT) * 0.08;
      recommendedFadeIn.material.opacity = o.fadeT * pulse;
      recommendedFadeIn.material.size = 3.2 + o.fadeT * 1.6;
      if (o.fadeT > 0.98) recommendedFadeIn = null;
    }
    if (recommendedFadeOut && recommendedFadeOut !== recommendedStars) {
      const o = recommendedFadeOut.userData;
      o.fadeT += (o.fadeTarget - o.fadeT) * 0.08;
      recommendedFadeOut.material.opacity = o.fadeT * pulse;
      recommendedFadeOut.material.size = 3.2 + o.fadeT * 1.6;
      if (o.fadeT < 0.02) {
        scene.remove(recommendedFadeOut);
        recommendedFadeOut.geometry.dispose();
        recommendedFadeOut.material.dispose();
        recommendedFadeOut = null;
      }
    }

    renderer.render(scene, camera);
  }

  function resize() {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  }
  window.addEventListener('resize', resize);

  placeCamera();
  tick();

  /* ---------- reshuffle triggers ----------
     app.js emits these facts (a chat turn finished, the radar changed, an
     action-plan step changed) without knowing anything about how often a
     reshuffle should actually happen - that throttle is scene.js's call,
     since it's the one that knows what "distracting" looks like here. */
  const RESHUFFLE_THROTTLE_MS = 25000;
  let lastReshuffleAt = 0;
  function onReshuffleTrigger(e) {
    const now = performance.now();
    if (now - lastReshuffleAt < RESHUFFLE_THROTTLE_MS) return;
    lastReshuffleAt = now;
    reshuffleRecommendedStars((e && e.detail && e.detail.promptIds) || []);
  }
  MR.bus.addEventListener('chat:completed', onReshuffleTrigger);
  MR.bus.addEventListener('radar:changed', onReshuffleTrigger);
  MR.bus.addEventListener('actionplan:changed', onReshuffleTrigger);

  /* ---------- public API ---------- */
  MR.scene = {
    focus, release, setStarMode,
    reshuffleStars: (promptIds) => reshuffleRecommendedStars(promptIds || []),
    get interactionLocked() { return isLocked(); }
  };
})();
