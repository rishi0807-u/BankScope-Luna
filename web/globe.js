/* Local orthographic Earth renderer. Boundaries: Natural Earth via world-atlas. */
window.BankGlobe = (() => {
  let topology, features, rotation=[-25,-18,0], zoom=1, spinning=false, dispose=()=>{}, selected='';
  const aliases={'United States of America':'United States','Czech Republic':'Czechia','Republic of Korea':'South Korea','Korea':'South Korea'};
  const name=f=>aliases[f.properties.name]||f.properties.name;
  async function load(){
    if(!features){
      const r=await fetch('/static/vendor/countries-50m.json');if(!r.ok)throw Error('Local globe boundary file could not be loaded.');
      topology=await r.json();features=topojson.feature(topology,topology.objects.countries).features;
      features.forEach(f=>{
        const parts=f.geometry.type==='MultiPolygon'?f.geometry.coordinates.map(c=>({type:'Polygon',coordinates:c})):[f.geometry];
        f.center=d3.geoCentroid(parts.sort((a,b)=>d3.geoArea(b)-d3.geoArea(a))[0]);
      });
    }
    return features;
  }
  async function mount({canvas,tooltip,available,counts,current,onSelect,onUnavailable}){
    dispose();await load();if(!canvas.isConnected)return;
    selected=current||'';let alive=true,frame,hover=null,drag=null,moved=false,last=0,width=600,height=530,markers=[];
    const ctx=canvas.getContext('2d'),valid=new Set(available),countMap=new Map(counts.map(x=>[x.country,x.customers]));
    const projection=d3.geoOrthographic().clipAngle(90).precision(.65),path=d3.geoPath(projection,ctx),grid=d3.geoGraticule10();
    let targetRotation=[...rotation], targetZoom=zoom, focusAnimating=false;
    function easeToward(current,target,ease){return current+(target-current)*ease;}
    function moveToTarget(){
      if(drag)return;
      let changed=false;
      if(focusAnimating){
        const nextRot0=easeToward(rotation[0],targetRotation[0],.08), nextRot1=easeToward(rotation[1],targetRotation[1],.08);
        const nextZoom=easeToward(zoom,targetZoom,.07);
        if(Math.abs(nextRot0-rotation[0])>1e-4 || Math.abs(nextRot1-rotation[1])>1e-4 || Math.abs(nextZoom-zoom)>1e-4){
          rotation[0]=nextRot0; rotation[1]=nextRot1; zoom=nextZoom; changed=true;
        }
        if(Math.abs(targetRotation[0]-rotation[0])<.05 && Math.abs(targetRotation[1]-rotation[1])<.05 && Math.abs(targetZoom-zoom)<.01){
          rotation=[...targetRotation]; zoom=targetZoom; focusAnimating=false;
          changed=true;
        }
      }
      if(changed || !focusAnimating) draw();
    }
    function resize(){const rect=canvas.parentElement.getBoundingClientRect();width=rect.width;height=Math.max(360,Math.min(590,width*.84));const ratio=Math.min(devicePixelRatio||1,2);canvas.width=width*ratio;canvas.height=height*ratio;canvas.style.height=height+'px';ctx.setTransform(ratio,0,0,ratio,0,0);draw();}
    function draw(){if(!alive)return;ctx.clearRect(0,0,width,height);const radius=Math.min(width,height)*.405*zoom,cx=width/2,cy=height/2;
      projection.translate([cx,cy]).scale(radius).rotate(rotation);
      const halo=ctx.createRadialGradient(cx,cy,radius*.95,cx,cy,radius*1.14);halo.addColorStop(0,'rgba(52,197,224,.18)');halo.addColorStop(1,'rgba(36,107,200,0)');ctx.fillStyle=halo;ctx.beginPath();ctx.arc(cx,cy,radius*1.14,0,Math.PI*2);ctx.fill();
      const ocean=ctx.createRadialGradient(cx-radius*.35,cy-radius*.45,0,cx,cy,radius*1.25);ocean.addColorStop(0,'#153956');ocean.addColorStop(.65,'#092239');ocean.addColorStop(1,'#030d1e');ctx.beginPath();path({type:'Sphere'});ctx.fillStyle=ocean;ctx.fill();ctx.strokeStyle='#246283';ctx.lineWidth=1;ctx.stroke();
      ctx.beginPath();path(grid);ctx.strokeStyle='rgba(107,185,224,.12)';ctx.lineWidth=.5;ctx.stroke();
      for(const f of features){const n=name(f);ctx.beginPath();path(f);ctx.fillStyle=n===selected?'#40dbc8':f===hover?'#91e5ec':valid.has(n)?'#376584':'#1d354a';ctx.fill();ctx.strokeStyle=n===selected?'#b9fff4':'#0b2439';ctx.lineWidth=n===selected?1.4:.65;ctx.stroke();}
      markers=[];const center=projection.invert([cx,cy]);
      for(const f of features){const n=name(f);if(!valid.has(n)||d3.geoDistance(center,f.center)>Math.PI/2-.025)continue;const p=projection(f.center);if(!p)continue;markers.push({p,f});ctx.beginPath();ctx.arc(...p,n===selected?5:2.6,0,Math.PI*2);ctx.fillStyle=n===selected?'#fff':(countMap.get(n)||0)>0?'#67d8d5':'#708796';ctx.fill();}
      ctx.beginPath();path({type:'Sphere'});ctx.strokeStyle='rgba(112,212,241,.35)';ctx.lineWidth=1;ctx.stroke();
    }
    function pointer(e){const r=canvas.getBoundingClientRect();return [e.clientX-r.left,e.clientY-r.top];}
    function hit(p){const [cx,cy]=projection.translate(),radius=projection.scale();if(Math.hypot(p[0]-cx,p[1]-cy)>radius)return null;const dot=markers.map(m=>({...m,d:Math.hypot(m.p[0]-p[0],m.p[1]-p[1])})).filter(m=>m.d<9).sort((a,b)=>a.d-b.d)[0];if(dot)return dot.f;const ll=projection.invert(p);return ll?features.find(f=>d3.geoContains(f,ll)):null;}
    function setSpin(value){spinning=value;const b=document.getElementById('globeSpin');if(b){b.textContent=spinning?'Pause rotation':'Auto-rotate';b.setAttribute('aria-pressed',String(spinning));}}
    function down(e){setSpin(false);targetRotation=[...rotation];canvas.focus();canvas.setPointerCapture(e.pointerId);drag={p:pointer(e),r:[...rotation]};moved=false;tooltip.hidden=true;canvas.style.cursor='grabbing';}
    function move(e){const p=pointer(e);if(drag){const dx=p[0]-drag.p[0],dy=p[1]-drag.p[1];moved ||= Math.hypot(dx,dy)>5;rotation=[drag.r[0]+dx*.3/zoom,Math.max(-85,Math.min(85,drag.r[1]-dy*.3/zoom)),0];targetRotation=[...rotation];focusAnimating=false;draw();return;}hover=hit(p);draw();canvas.style.cursor=hover?'pointer':'grab';tooltip.hidden=!hover;if(hover){const n=name(hover);tooltip.textContent=valid.has(n)?`${n} · ${(countMap.get(n)||0).toLocaleString()} matching records`:`${n} · No dataset records`;tooltip.style.left=Math.min(p[0]+14,width-235)+'px';tooltip.style.top=Math.max(8,p[1]-40)+'px';}}
    function up(e){if(!drag)return;drag=null;canvas.style.cursor='grab';if(!moved){const f=hit(pointer(e));if(f){const n=name(f);if(valid.has(n)){selected=n;focus(n,true);onSelect(n);}else onUnavailable(n);}}}
    function wheel(e){e.preventDefault();zoom=Math.max(.7,Math.min(2.4,zoom*(e.deltaY>0?.94:1.06)));targetZoom=zoom;draw();}
    function key(e){const dirs={ArrowLeft:[-10,0],ArrowRight:[10,0],ArrowUp:[0,10],ArrowDown:[0,-10]};if(dirs[e.key]){e.preventDefault();setSpin(false);rotation[0]+=dirs[e.key][0];rotation[1]=Math.max(-85,Math.min(85,rotation[1]+dirs[e.key][1]));targetRotation=[...rotation];targetZoom=zoom;focusAnimating=false;draw();}if(e.key==='+'||e.key==='='){zoom=Math.min(2.4,zoom+.15);targetZoom=zoom;draw();}if(e.key==='-'){zoom=Math.max(.7,zoom-.15);targetZoom=zoom;draw();}}
    const leave=()=>{tooltip.hidden=true;hover=null;draw();};
    canvas.addEventListener('pointerdown',down);canvas.addEventListener('pointermove',move);canvas.addEventListener('pointerup',up);canvas.addEventListener('pointercancel',()=>{drag=null});canvas.addEventListener('pointerleave',leave);canvas.addEventListener('wheel',wheel,{passive:false});canvas.addEventListener('keydown',key);
    const observer=new ResizeObserver(resize);observer.observe(canvas.parentElement);resize();
    function tick(t){if(!alive)return;if(spinning&&!drag&&t-last>32){rotation[0]+=.18;targetRotation=[...rotation];last=t;}else if(!drag){moveToTarget();}if(!focusAnimating && !spinning && !drag && t-last>32){draw();}frame=requestAnimationFrame(tick);}frame=requestAnimationFrame(tick);
    function focus(n,animate=false){const f=features.find(f=>name(f)===n);if(!f)return;setSpin(false);selected=n;const target=[-f.center[0],-f.center[1],0];if(!animate){rotation=[...target];targetRotation=[...target];zoom=Math.max(1.05,Math.min(1.9,zoom));targetZoom=zoom;draw();return;}targetRotation=[...target];targetZoom=Math.min(1.9,Math.max(1.2,zoom+0.35));focusAnimating=true;}
    const control=(id,fn)=>{const el=document.getElementById(id);if(el)el.onclick=fn;};
    control('globeSpin',()=>{setSpin(!spinning);if(!spinning){targetRotation=[...rotation];targetZoom=zoom;focusAnimating=false;}});control('globeZoomIn',()=>{zoom=Math.min(2.4,zoom+.2);targetZoom=zoom;draw();});control('globeZoomOut',()=>{zoom=Math.max(.7,zoom-.2);targetZoom=zoom;draw();});control('globeReset',()=>{rotation=[-25,-18,0];targetRotation=[...rotation];zoom=1;targetZoom=1;focusAnimating=false;draw()});setSpin(spinning);
    if(current)focus(current,false);
    dispose=()=>{alive=false;cancelAnimationFrame(frame);observer.disconnect();};
    return {focus,availableNames:features.map(name)};
  }
  return {mount,destroy:()=>dispose(),load};
})();
