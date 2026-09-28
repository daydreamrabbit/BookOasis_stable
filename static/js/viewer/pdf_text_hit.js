export function pdfTextRects(content, viewport) {
  const [a,b,c,d,e,f] = viewport.transform;
  return content.items.filter(item => item.str?.trim() && item.transform).map(item => {
    const [u,v,w,z,x,y] = item.transform;
    const angle = Math.atan2(b*u+d*v, a*u+c*v);
    const height = Math.hypot(a*w+c*z, b*w+d*z);
    const width = Math.abs(item.width * viewport.scale);
    const ascent = content.styles?.[item.fontName]?.ascent ?? .85;
    const px=a*x+c*y+e, py=b*x+d*y+f;
    const cos=Math.cos(angle), sin=Math.sin(angle);
    const corners=[[-height*ascent,0],[-height*ascent,width],[height*(1-ascent),0],[height*(1-ascent),width]]
      .map(([h,s])=>[px+s*cos-h*sin,py+s*sin+h*cos]);
    return {left:Math.min(...corners.map(p=>p[0])),right:Math.max(...corners.map(p=>p[0])),
      top:Math.min(...corners.map(p=>p[1])),bottom:Math.max(...corners.map(p=>p[1]))};
  });
}
