import{g as He,s as Be,x as qe,v as Ge,a as Xe,b as je,_ as l,c as ht,k as bt,d as Ue,b1 as U,l as it,m as Ze,p as Qe,D as Ke,u as Je}from"./mermaid.core-Dybq5xf8.js";import{g as Ft}from"./react-runtime-Sh9D8V6S.js";import{d as tn,r as en,t as nn,a as ae,b as oe,c as rn,e as sn,f as an,g as on,h as cn,i as ln,j as un,k as ce,l as le,m as ue,s as de,n as fe}from"./time-C0FsENn2.js";import{l as dn}from"./linear-DSDPEtUH.js";import{R as Te,r as fn,o as be,q as we,C as _e,u as Ot,v as hn}from"./step-v8IoTKFH.js";import"./index-WD5TeMGp.js";import"./i18n-runtime-CtZKKeGo.js";import"./init-Gi6I4Gst.js";import"./defaultLocale-DX6XiGOO.js";const $t=18,De=.96422,Se=1,Ce=.82521,Me=4/29,mt=6/29,Ee=3*mt*mt,mn=mt*mt*mt;function Ie(t){if(t instanceof nt)return new nt(t.l,t.a,t.b,t.opacity);if(t instanceof st)return $e(t);t instanceof Te||(t=fn(t));var e=Vt(t.r),n=Vt(t.g),r=Vt(t.b),i=Wt((.2225045*e+.7168786*n+.0606169*r)/Se),m,f;return e===n&&n===r?m=f=i:(m=Wt((.4360747*e+.3850649*n+.1430804*r)/De),f=Wt((.0139322*e+.0971045*n+.7141733*r)/Ce)),new nt(116*i-16,500*(m-i),200*(i-f),t.opacity)}function kn(t,e,n,r){return arguments.length===1?Ie(t):new nt(t,e,n,r??1)}function nt(t,e,n,r){this.l=+t,this.a=+e,this.b=+n,this.opacity=+r}be(nt,kn,we(_e,{brighter(t){return new nt(this.l+$t*(t??1),this.a,this.b,this.opacity)},darker(t){return new nt(this.l-$t*(t??1),this.a,this.b,this.opacity)},rgb(){var t=(this.l+16)/116,e=isNaN(this.a)?t:t+this.a/500,n=isNaN(this.b)?t:t-this.b/200;return e=De*Nt(e),t=Se*Nt(t),n=Ce*Nt(n),new Te(Pt(3.1338561*e-1.6168667*t-.4906146*n),Pt(-.9787684*e+1.9161415*t+.033454*n),Pt(.0719453*e-.2289914*t+1.4052427*n),this.opacity)}}));function Wt(t){return t>mn?Math.pow(t,1/3):t/Ee+Me}function Nt(t){return t>mt?t*t*t:Ee*(t-Me)}function Pt(t){return 255*(t<=.0031308?12.92*t:1.055*Math.pow(t,1/2.4)-.055)}function Vt(t){return(t/=255)<=.04045?t/12.92:Math.pow((t+.055)/1.055,2.4)}function yn(t){if(t instanceof st)return new st(t.h,t.c,t.l,t.opacity);if(t instanceof nt||(t=Ie(t)),t.a===0&&t.b===0)return new st(NaN,0<t.l&&t.l<100?0:NaN,t.l,t.opacity);var e=Math.atan2(t.b,t.a)*tn;return new st(e<0?e+360:e,Math.sqrt(t.a*t.a+t.b*t.b),t.l,t.opacity)}function Ht(t,e,n,r){return arguments.length===1?yn(t):new st(t,e,n,r??1)}function st(t,e,n,r){this.h=+t,this.c=+e,this.l=+n,this.opacity=+r}function $e(t){if(isNaN(t.h))return new nt(t.l,0,0,t.opacity);var e=t.h*en;return new nt(t.l,Math.cos(e)*t.c,Math.sin(e)*t.c,t.opacity)}be(st,Ht,we(_e,{brighter(t){return new st(this.h,this.c,this.l+$t*(t??1),this.opacity)},darker(t){return new st(this.h,this.c,this.l-$t*(t??1),this.opacity)},rgb(){return $e(this).rgb()}}));function gn(t){return function(e,n){var r=t((e=Ht(e)).h,(n=Ht(n)).h),i=Ot(e.c,n.c),m=Ot(e.l,n.l),f=Ot(e.opacity,n.opacity);return function(b){return e.h=r(b),e.c=i(b),e.l=m(b),e.opacity=f(b),e+""}}}const pn=gn(hn);function vn(t,e){let n;if(e===void 0)for(const r of t)r!=null&&(n<r||n===void 0&&r>=r)&&(n=r);else{let r=-1;for(let i of t)(i=e(i,++r,t))!=null&&(n<i||n===void 0&&i>=i)&&(n=i)}return n}function xn(t,e){let n;if(e===void 0)for(const r of t)r!=null&&(n>r||n===void 0&&r>=r)&&(n=r);else{let r=-1;for(let i of t)(i=e(i,++r,t))!=null&&(n>i||n===void 0&&i>=i)&&(n=i)}return n}function Tn(t){return t}var _t=1,zt=2,Bt=3,wt=4,he=1e-6;function bn(t){return"translate("+t+",0)"}function wn(t){return"translate(0,"+t+")"}function _n(t){return e=>+t(e)}function Dn(t,e){return e=Math.max(0,t.bandwidth()-e*2)/2,t.round()&&(e=Math.round(e)),n=>+t(n)+e}function Sn(){return!this.__axis}function Ye(t,e){var n=[],r=null,i=null,m=6,f=6,b=3,S=typeof window<"u"&&window.devicePixelRatio>1?0:.5,L=t===_t||t===wt?-1:1,_=t===wt||t===zt?"x":"y",W=t===_t||t===Bt?bn:wn;function w(D){var R=r??(e.ticks?e.ticks.apply(e,n):e.domain()),P=i??(e.tickFormat?e.tickFormat.apply(e,n):Tn),g=Math.max(m,0)+b,M=e.range(),N=+M[0]+S,O=+M[M.length-1]+S,B=(e.bandwidth?Dn:_n)(e.copy(),S),H=D.selection?D.selection():D,I=H.selectAll(".domain").data([null]),x=H.selectAll(".tick").data(R,e).order(),k=x.exit(),E=x.enter().append("g").attr("class","tick"),h=x.select("line"),T=x.select("text");I=I.merge(I.enter().insert("path",".tick").attr("class","domain").attr("stroke","currentColor")),x=x.merge(E),h=h.merge(E.append("line").attr("stroke","currentColor").attr(_+"2",L*m)),T=T.merge(E.append("text").attr("fill","currentColor").attr(_,L*g).attr("dy",t===_t?"0em":t===Bt?"0.71em":"0.32em")),D!==H&&(I=I.transition(D),x=x.transition(D),h=h.transition(D),T=T.transition(D),k=k.transition(D).attr("opacity",he).attr("transform",function(v){return isFinite(v=B(v))?W(v+S):this.getAttribute("transform")}),E.attr("opacity",he).attr("transform",function(v){var p=this.parentNode.__axis;return W((p&&isFinite(p=p(v))?p:B(v))+S)})),k.remove(),I.attr("d",t===wt||t===zt?f?"M"+L*f+","+N+"H"+S+"V"+O+"H"+L*f:"M"+S+","+N+"V"+O:f?"M"+N+","+L*f+"V"+S+"H"+O+"V"+L*f:"M"+N+","+S+"H"+O),x.attr("opacity",1).attr("transform",function(v){return W(B(v)+S)}),h.attr(_+"2",L*m),T.attr(_,L*g).text(P),H.filter(Sn).attr("fill","none").attr("font-size",10).attr("font-family","sans-serif").attr("text-anchor",t===zt?"start":t===wt?"end":"middle"),H.each(function(){this.__axis=B})}return w.scale=function(D){return arguments.length?(e=D,w):e},w.ticks=function(){return n=Array.from(arguments),w},w.tickArguments=function(D){return arguments.length?(n=D==null?[]:Array.from(D),w):n.slice()},w.tickValues=function(D){return arguments.length?(r=D==null?null:Array.from(D),w):r&&r.slice()},w.tickFormat=function(D){return arguments.length?(i=D,w):i},w.tickSize=function(D){return arguments.length?(m=f=+D,w):m},w.tickSizeInner=function(D){return arguments.length?(m=+D,w):m},w.tickSizeOuter=function(D){return arguments.length?(f=+D,w):f},w.tickPadding=function(D){return arguments.length?(b=+D,w):b},w.offset=function(D){return arguments.length?(S=+D,w):S},w}function Cn(t){return Ye(_t,t)}function Mn(t){return Ye(Bt,t)}var Dt={exports:{}},En=Dt.exports,me;function In(){return me||(me=1,(function(t,e){(function(n,r){t.exports=r()})(En,(function(){var n="day";return function(r,i,m){var f=function(L){return L.add(4-L.isoWeekday(),n)},b=i.prototype;b.isoWeekYear=function(){return f(this).year()},b.isoWeek=function(L){if(!this.$utils().u(L))return this.add(7*(L-this.isoWeek()),n);var _,W,w,D,R=f(this),P=(_=this.isoWeekYear(),W=this.$u,w=(W?m.utc:m)().year(_).startOf("year"),D=4-w.isoWeekday(),w.isoWeekday()>4&&(D+=7),w.add(D,n));return R.diff(P,"week")+1},b.isoWeekday=function(L){return this.$utils().u(L)?this.day()||7:this.day(this.day()%7?L:L-7)};var S=b.startOf;b.startOf=function(L,_){var W=this.$utils(),w=!!W.u(_)||_;return W.p(L)==="isoweek"?w?this.date(this.date()-(this.isoWeekday()-1)).startOf("day"):this.date(this.date()-1-(this.isoWeekday()-1)+7).endOf("day"):S.bind(this)(L,_)}}}))})(Dt)),Dt.exports}var $n=In();const Yn=Ft($n);var St={exports:{}},An=St.exports,ke;function Fn(){return ke||(ke=1,(function(t,e){(function(n,r){t.exports=r()})(An,(function(){var n={LTS:"h:mm:ss A",LT:"h:mm A",L:"MM/DD/YYYY",LL:"MMMM D, YYYY",LLL:"MMMM D, YYYY h:mm A",LLLL:"dddd, MMMM D, YYYY h:mm A"},r=/(\[[^[]*\])|([-_:/.,()\s]+)|(A|a|Q|YYYY|YY?|ww?|MM?M?M?|Do|DD?|hh?|HH?|mm?|ss?|S{1,3}|z|ZZ?)/g,i=/\d/,m=/\d\d/,f=/\d\d?/,b=/\d*[^-_:/,()\s\d]+/,S={},L=function(g){return(g=+g)+(g>68?1900:2e3)},_=function(g){return function(M){this[g]=+M}},W=[/[+-]\d\d:?(\d\d)?|Z/,function(g){(this.zone||(this.zone={})).offset=(function(M){if(!M||M==="Z")return 0;var N=M.match(/([+-]|\d\d)/g),O=60*N[1]+(+N[2]||0);return O===0?0:N[0]==="+"?-O:O})(g)}],w=function(g){var M=S[g];return M&&(M.indexOf?M:M.s.concat(M.f))},D=function(g,M){var N,O=S.meridiem;if(O){for(var B=1;B<=24;B+=1)if(g.indexOf(O(B,0,M))>-1){N=B>12;break}}else N=g===(M?"pm":"PM");return N},R={A:[b,function(g){this.afternoon=D(g,!1)}],a:[b,function(g){this.afternoon=D(g,!0)}],Q:[i,function(g){this.month=3*(g-1)+1}],S:[i,function(g){this.milliseconds=100*+g}],SS:[m,function(g){this.milliseconds=10*+g}],SSS:[/\d{3}/,function(g){this.milliseconds=+g}],s:[f,_("seconds")],ss:[f,_("seconds")],m:[f,_("minutes")],mm:[f,_("minutes")],H:[f,_("hours")],h:[f,_("hours")],HH:[f,_("hours")],hh:[f,_("hours")],D:[f,_("day")],DD:[m,_("day")],Do:[b,function(g){var M=S.ordinal,N=g.match(/\d+/);if(this.day=N[0],M)for(var O=1;O<=31;O+=1)M(O).replace(/\[|\]/g,"")===g&&(this.day=O)}],w:[f,_("week")],ww:[m,_("week")],M:[f,_("month")],MM:[m,_("month")],MMM:[b,function(g){var M=w("months"),N=(w("monthsShort")||M.map((function(O){return O.slice(0,3)}))).indexOf(g)+1;if(N<1)throw new Error;this.month=N%12||N}],MMMM:[b,function(g){var M=w("months").indexOf(g)+1;if(M<1)throw new Error;this.month=M%12||M}],Y:[/[+-]?\d+/,_("year")],YY:[m,function(g){this.year=L(g)}],YYYY:[/\d{4}/,_("year")],Z:W,ZZ:W};function P(g){var M,N;M=g,N=S&&S.formats;for(var O=(g=M.replace(/(\[[^\]]+])|(LTS?|l{1,4}|L{1,4})/g,(function(h,T,v){var p=v&&v.toUpperCase();return T||N[v]||n[v]||N[p].replace(/(\[[^\]]+])|(MMMM|MM|DD|dddd)/g,(function(a,d,y){return d||y.slice(1)}))}))).match(r),B=O.length,H=0;H<B;H+=1){var I=O[H],x=R[I],k=x&&x[0],E=x&&x[1];O[H]=E?{regex:k,parser:E}:I.replace(/^\[|\]$/g,"")}return function(h){for(var T={},v=0,p=0;v<B;v+=1){var a=O[v];if(typeof a=="string")p+=a.length;else{var d=a.regex,y=a.parser,u=h.slice(p),C=d.exec(u)[0];y.call(T,C),h=h.replace(C,"")}}return(function(s){var $=s.afternoon;if($!==void 0){var o=s.hours;$?o<12&&(s.hours+=12):o===12&&(s.hours=0),delete s.afternoon}})(T),T}}return function(g,M,N){N.p.customParseFormat=!0,g&&g.parseTwoDigitYear&&(L=g.parseTwoDigitYear);var O=M.prototype,B=O.parse;O.parse=function(H){var I=H.date,x=H.utc,k=H.args;this.$u=x;var E=k[1];if(typeof E=="string"){var h=k[2]===!0,T=k[3]===!0,v=h||T,p=k[2];T&&(p=k[2]),S=this.$locale(),!h&&p&&(S=N.Ls[p]),this.$d=(function(u,C,s,$){try{if(["x","X"].indexOf(C)>-1)return new Date((C==="X"?1e3:1)*u);var o=P(C)(u),G=o.year,c=o.month,Y=o.day,A=o.hours,z=o.minutes,F=o.seconds,q=o.milliseconds,V=o.zone,at=o.week,ct=new Date,vt=Y||(G||c?1:ct.getDate()),dt=G||ct.getFullYear(),X=0;G&&!c||(X=c>0?c-1:ct.getMonth());var K,Z=A||0,lt=z||0,J=F||0,ot=q||0;return V?new Date(Date.UTC(dt,X,vt,Z,lt,J,ot+60*V.offset*1e3)):s?new Date(Date.UTC(dt,X,vt,Z,lt,J,ot)):(K=new Date(dt,X,vt,Z,lt,J,ot),at&&(K=$(K).week(at).toDate()),K)}catch{return new Date("")}})(I,E,x,N),this.init(),p&&p!==!0&&(this.$L=this.locale(p).$L),v&&I!=this.format(E)&&(this.$d=new Date("")),S={}}else if(E instanceof Array)for(var a=E.length,d=1;d<=a;d+=1){k[1]=E[d-1];var y=N.apply(this,k);if(y.isValid()){this.$d=y.$d,this.$L=y.$L,this.init();break}d===a&&(this.$d=new Date(""))}else B.call(this,H)}}}))})(St)),St.exports}var Ln=Fn();const On=Ft(Ln);var Ct={exports:{}},Wn=Ct.exports,ye;function Nn(){return ye||(ye=1,(function(t,e){(function(n,r){t.exports=r()})(Wn,(function(){return function(n,r){var i=r.prototype,m=i.format;i.format=function(f){var b=this,S=this.$locale();if(!this.isValid())return m.bind(this)(f);var L=this.$utils(),_=(f||"YYYY-MM-DDTHH:mm:ssZ").replace(/\[([^\]]+)]|Q|wo|ww|w|WW|W|zzz|z|gggg|GGGG|Do|X|x|k{1,2}|S/g,(function(W){switch(W){case"Q":return Math.ceil((b.$M+1)/3);case"Do":return S.ordinal(b.$D);case"gggg":return b.weekYear();case"GGGG":return b.isoWeekYear();case"wo":return S.ordinal(b.week(),"W");case"w":case"ww":return L.s(b.week(),W==="w"?1:2,"0");case"W":case"WW":return L.s(b.isoWeek(),W==="W"?1:2,"0");case"k":case"kk":return L.s(String(b.$H===0?24:b.$H),W==="k"?1:2,"0");case"X":return Math.floor(b.$d.getTime()/1e3);case"x":return b.$d.getTime();case"z":return"["+b.offsetName()+"]";case"zzz":return"["+b.offsetName("long")+"]";default:return W}}));return m.bind(this)(_)}}}))})(Ct)),Ct.exports}var Pn=Nn();const Vn=Ft(Pn);var Mt={exports:{}},zn=Mt.exports,ge;function Rn(){return ge||(ge=1,(function(t,e){(function(n,r){t.exports=r()})(zn,(function(){var n,r,i=1e3,m=6e4,f=36e5,b=864e5,S=31536e6,L=2628e6,_=/^(-|\+)?P(?:([-+]?[0-9,.]*)Y)?(?:([-+]?[0-9,.]*)M)?(?:([-+]?[0-9,.]*)W)?(?:([-+]?[0-9,.]*)D)?(?:T(?:([-+]?[0-9,.]*)H)?(?:([-+]?[0-9,.]*)M)?(?:([-+]?[0-9,.]*)S)?)?$/,W=/\[([^\]]+)]|YYYY|YY|Y|M{1,2}|D{1,2}|H{1,2}|m{1,2}|s{1,2}|SSS/g,w={years:S,months:L,days:b,hours:f,minutes:m,seconds:i,milliseconds:1,weeks:6048e5},D=function(I){return I instanceof B},R=function(I,x,k){return new B(I,k,x.$l)},P=function(I){return r.p(I)+"s"},g=function(I){return I<0},M=function(I){return g(I)?Math.ceil(I):Math.floor(I)},N=function(I){return Math.abs(I)},O=function(I,x){return I?g(I)?{negative:!0,format:""+N(I)+x}:{negative:!1,format:""+I+x}:{negative:!1,format:""}},B=(function(){function I(k,E,h){var T=this;if(this.$d={},this.$l=h,k===void 0&&(this.$ms=0,this.parseFromMilliseconds()),E)return R(k*w[P(E)],this);if(typeof k=="number")return this.$ms=k,this.parseFromMilliseconds(),this;if(typeof k=="object")return Object.keys(k).forEach((function(a){T.$d[P(a)]=k[a]})),this.calMilliseconds(),this;if(typeof k=="string"){var v=k.match(_);if(v){var p=v.slice(2).map((function(a){return a!=null?Number(a):0}));return this.$d.years=p[0],this.$d.months=p[1],this.$d.weeks=p[2],this.$d.days=p[3],this.$d.hours=p[4],this.$d.minutes=p[5],this.$d.seconds=p[6],this.calMilliseconds(),this}}return this}var x=I.prototype;return x.calMilliseconds=function(){var k=this;this.$ms=Object.keys(this.$d).reduce((function(E,h){return E+(k.$d[h]||0)*w[h]}),0)},x.parseFromMilliseconds=function(){var k=this.$ms;this.$d.years=M(k/S),k%=S,this.$d.months=M(k/L),k%=L,this.$d.days=M(k/b),k%=b,this.$d.hours=M(k/f),k%=f,this.$d.minutes=M(k/m),k%=m,this.$d.seconds=M(k/i),k%=i,this.$d.milliseconds=k},x.toISOString=function(){var k=O(this.$d.years,"Y"),E=O(this.$d.months,"M"),h=+this.$d.days||0;this.$d.weeks&&(h+=7*this.$d.weeks);var T=O(h,"D"),v=O(this.$d.hours,"H"),p=O(this.$d.minutes,"M"),a=this.$d.seconds||0;this.$d.milliseconds&&(a+=this.$d.milliseconds/1e3,a=Math.round(1e3*a)/1e3);var d=O(a,"S"),y=k.negative||E.negative||T.negative||v.negative||p.negative||d.negative,u=v.format||p.format||d.format?"T":"",C=(y?"-":"")+"P"+k.format+E.format+T.format+u+v.format+p.format+d.format;return C==="P"||C==="-P"?"P0D":C},x.toJSON=function(){return this.toISOString()},x.format=function(k){var E=k||"YYYY-MM-DDTHH:mm:ss",h={Y:this.$d.years,YY:r.s(this.$d.years,2,"0"),YYYY:r.s(this.$d.years,4,"0"),M:this.$d.months,MM:r.s(this.$d.months,2,"0"),D:this.$d.days,DD:r.s(this.$d.days,2,"0"),H:this.$d.hours,HH:r.s(this.$d.hours,2,"0"),m:this.$d.minutes,mm:r.s(this.$d.minutes,2,"0"),s:this.$d.seconds,ss:r.s(this.$d.seconds,2,"0"),SSS:r.s(this.$d.milliseconds,3,"0")};return E.replace(W,(function(T,v){return v||String(h[T])}))},x.as=function(k){return this.$ms/w[P(k)]},x.get=function(k){var E=this.$ms,h=P(k);return h==="milliseconds"?E%=1e3:E=h==="weeks"?M(E/w[h]):this.$d[h],E||0},x.add=function(k,E,h){var T;return T=E?k*w[P(E)]:D(k)?k.$ms:R(k,this).$ms,R(this.$ms+T*(h?-1:1),this)},x.subtract=function(k,E){return this.add(k,E,!0)},x.locale=function(k){var E=this.clone();return E.$l=k,E},x.clone=function(){return R(this.$ms,this)},x.humanize=function(k){return n().add(this.$ms,"ms").locale(this.$l).fromNow(!k)},x.valueOf=function(){return this.asMilliseconds()},x.milliseconds=function(){return this.get("milliseconds")},x.asMilliseconds=function(){return this.as("milliseconds")},x.seconds=function(){return this.get("seconds")},x.asSeconds=function(){return this.as("seconds")},x.minutes=function(){return this.get("minutes")},x.asMinutes=function(){return this.as("minutes")},x.hours=function(){return this.get("hours")},x.asHours=function(){return this.as("hours")},x.days=function(){return this.get("days")},x.asDays=function(){return this.as("days")},x.weeks=function(){return this.get("weeks")},x.asWeeks=function(){return this.as("weeks")},x.months=function(){return this.get("months")},x.asMonths=function(){return this.as("months")},x.years=function(){return this.get("years")},x.asYears=function(){return this.as("years")},I})(),H=function(I,x,k){return I.add(x.years()*k,"y").add(x.months()*k,"M").add(x.days()*k,"d").add(x.hours()*k,"h").add(x.minutes()*k,"m").add(x.seconds()*k,"s").add(x.milliseconds()*k,"ms")};return function(I,x,k){n=k,r=k().$utils(),k.duration=function(T,v){var p=k.locale();return R(T,{$l:p},v)},k.isDuration=D;var E=x.prototype.add,h=x.prototype.subtract;x.prototype.add=function(T,v){return D(T)?H(this,T,1):E.bind(this)(T,v)},x.prototype.subtract=function(T,v){return D(T)?H(this,T,-1):h.bind(this)(T,v)}}}))})(Mt)),Mt.exports}var Hn=Rn();const Bn=Ft(Hn);var qt=(function(){var t=l(function(p,a,d,y){for(d=d||{},y=p.length;y--;d[p[y]]=a);return d},"o"),e=[6,8,10,12,13,14,15,16,17,18,20,21,22,23,24,25,26,27,28,29,30,31,33,35,36,38,40],n=[1,26],r=[1,27],i=[1,28],m=[1,29],f=[1,30],b=[1,31],S=[1,32],L=[1,33],_=[1,34],W=[1,9],w=[1,10],D=[1,11],R=[1,12],P=[1,13],g=[1,14],M=[1,15],N=[1,16],O=[1,19],B=[1,20],H=[1,21],I=[1,22],x=[1,23],k=[1,25],E=[1,35],h={trace:l(function(){},"trace"),yy:{},symbols_:{error:2,start:3,gantt:4,document:5,EOF:6,line:7,SPACE:8,statement:9,NL:10,weekday:11,weekday_monday:12,weekday_tuesday:13,weekday_wednesday:14,weekday_thursday:15,weekday_friday:16,weekday_saturday:17,weekday_sunday:18,weekend:19,weekend_friday:20,weekend_saturday:21,dateFormat:22,inclusiveEndDates:23,topAxis:24,axisFormat:25,tickInterval:26,excludes:27,includes:28,todayMarker:29,title:30,acc_title:31,acc_title_value:32,acc_descr:33,acc_descr_value:34,acc_descr_multiline_value:35,section:36,clickStatement:37,taskTxt:38,taskData:39,click:40,callbackname:41,callbackargs:42,href:43,clickStatementDebug:44,$accept:0,$end:1},terminals_:{2:"error",4:"gantt",6:"EOF",8:"SPACE",10:"NL",12:"weekday_monday",13:"weekday_tuesday",14:"weekday_wednesday",15:"weekday_thursday",16:"weekday_friday",17:"weekday_saturday",18:"weekday_sunday",20:"weekend_friday",21:"weekend_saturday",22:"dateFormat",23:"inclusiveEndDates",24:"topAxis",25:"axisFormat",26:"tickInterval",27:"excludes",28:"includes",29:"todayMarker",30:"title",31:"acc_title",32:"acc_title_value",33:"acc_descr",34:"acc_descr_value",35:"acc_descr_multiline_value",36:"section",38:"taskTxt",39:"taskData",40:"click",41:"callbackname",42:"callbackargs",43:"href"},productions_:[0,[3,3],[5,0],[5,2],[7,2],[7,1],[7,1],[7,1],[11,1],[11,1],[11,1],[11,1],[11,1],[11,1],[11,1],[19,1],[19,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,2],[9,2],[9,1],[9,1],[9,1],[9,2],[37,2],[37,3],[37,3],[37,4],[37,3],[37,4],[37,2],[44,2],[44,3],[44,3],[44,4],[44,3],[44,4],[44,2]],performAction:l(function(a,d,y,u,C,s,$){var o=s.length-1;switch(C){case 1:return s[o-1];case 2:this.$=[];break;case 3:s[o-1].push(s[o]),this.$=s[o-1];break;case 4:case 5:this.$=s[o];break;case 6:case 7:this.$=[];break;case 8:u.setWeekday("monday");break;case 9:u.setWeekday("tuesday");break;case 10:u.setWeekday("wednesday");break;case 11:u.setWeekday("thursday");break;case 12:u.setWeekday("friday");break;case 13:u.setWeekday("saturday");break;case 14:u.setWeekday("sunday");break;case 15:u.setWeekend("friday");break;case 16:u.setWeekend("saturday");break;case 17:u.setDateFormat(s[o].substr(11)),this.$=s[o].substr(11);break;case 18:u.enableInclusiveEndDates(),this.$=s[o].substr(18);break;case 19:u.TopAxis(),this.$=s[o].substr(8);break;case 20:u.setAxisFormat(s[o].substr(11)),this.$=s[o].substr(11);break;case 21:u.setTickInterval(s[o].substr(13)),this.$=s[o].substr(13);break;case 22:u.setExcludes(s[o].substr(9)),this.$=s[o].substr(9);break;case 23:u.setIncludes(s[o].substr(9)),this.$=s[o].substr(9);break;case 24:u.setTodayMarker(s[o].substr(12)),this.$=s[o].substr(12);break;case 27:u.setDiagramTitle(s[o].substr(6)),this.$=s[o].substr(6);break;case 28:this.$=s[o].trim(),u.setAccTitle(this.$);break;case 29:case 30:this.$=s[o].trim(),u.setAccDescription(this.$);break;case 31:u.addSection(s[o].substr(8)),this.$=s[o].substr(8);break;case 33:u.addTask(s[o-1],s[o]),this.$="task";break;case 34:this.$=s[o-1],u.setClickEvent(s[o-1],s[o],null);break;case 35:this.$=s[o-2],u.setClickEvent(s[o-2],s[o-1],s[o]);break;case 36:this.$=s[o-2],u.setClickEvent(s[o-2],s[o-1],null),u.setLink(s[o-2],s[o]);break;case 37:this.$=s[o-3],u.setClickEvent(s[o-3],s[o-2],s[o-1]),u.setLink(s[o-3],s[o]);break;case 38:this.$=s[o-2],u.setClickEvent(s[o-2],s[o],null),u.setLink(s[o-2],s[o-1]);break;case 39:this.$=s[o-3],u.setClickEvent(s[o-3],s[o-1],s[o]),u.setLink(s[o-3],s[o-2]);break;case 40:this.$=s[o-1],u.setLink(s[o-1],s[o]);break;case 41:case 47:this.$=s[o-1]+" "+s[o];break;case 42:case 43:case 45:this.$=s[o-2]+" "+s[o-1]+" "+s[o];break;case 44:case 46:this.$=s[o-3]+" "+s[o-2]+" "+s[o-1]+" "+s[o];break}},"anonymous"),table:[{3:1,4:[1,2]},{1:[3]},t(e,[2,2],{5:3}),{6:[1,4],7:5,8:[1,6],9:7,10:[1,8],11:17,12:n,13:r,14:i,15:m,16:f,17:b,18:S,19:18,20:L,21:_,22:W,23:w,24:D,25:R,26:P,27:g,28:M,29:N,30:O,31:B,33:H,35:I,36:x,37:24,38:k,40:E},t(e,[2,7],{1:[2,1]}),t(e,[2,3]),{9:36,11:17,12:n,13:r,14:i,15:m,16:f,17:b,18:S,19:18,20:L,21:_,22:W,23:w,24:D,25:R,26:P,27:g,28:M,29:N,30:O,31:B,33:H,35:I,36:x,37:24,38:k,40:E},t(e,[2,5]),t(e,[2,6]),t(e,[2,17]),t(e,[2,18]),t(e,[2,19]),t(e,[2,20]),t(e,[2,21]),t(e,[2,22]),t(e,[2,23]),t(e,[2,24]),t(e,[2,25]),t(e,[2,26]),t(e,[2,27]),{32:[1,37]},{34:[1,38]},t(e,[2,30]),t(e,[2,31]),t(e,[2,32]),{39:[1,39]},t(e,[2,8]),t(e,[2,9]),t(e,[2,10]),t(e,[2,11]),t(e,[2,12]),t(e,[2,13]),t(e,[2,14]),t(e,[2,15]),t(e,[2,16]),{41:[1,40],43:[1,41]},t(e,[2,4]),t(e,[2,28]),t(e,[2,29]),t(e,[2,33]),t(e,[2,34],{42:[1,42],43:[1,43]}),t(e,[2,40],{41:[1,44]}),t(e,[2,35],{43:[1,45]}),t(e,[2,36]),t(e,[2,38],{42:[1,46]}),t(e,[2,37]),t(e,[2,39])],defaultActions:{},parseError:l(function(a,d){if(d.recoverable)this.trace(a);else{var y=new Error(a);throw y.hash=d,y}},"parseError"),parse:l(function(a){var d=this,y=[0],u=[],C=[null],s=[],$=this.table,o="",G=0,c=0,Y=2,A=1,z=s.slice.call(arguments,1),F=Object.create(this.lexer),q={yy:{}};for(var V in this.yy)Object.prototype.hasOwnProperty.call(this.yy,V)&&(q.yy[V]=this.yy[V]);F.setInput(a,q.yy),q.yy.lexer=F,q.yy.parser=this,typeof F.yylloc>"u"&&(F.yylloc={});var at=F.yylloc;s.push(at);var ct=F.options&&F.options.ranges;typeof q.yy.parseError=="function"?this.parseError=q.yy.parseError:this.parseError=Object.getPrototypeOf(this).parseError;function vt(Q){y.length=y.length-2*Q,C.length=C.length-Q,s.length=s.length-Q}l(vt,"popStack");function dt(){var Q;return Q=u.pop()||F.lex()||A,typeof Q!="number"&&(Q instanceof Array&&(u=Q,Q=u.pop()),Q=d.symbols_[Q]||Q),Q}l(dt,"lex");for(var X,K,Z,lt,J={},ot,tt,se,Tt;;){if(K=y[y.length-1],this.defaultActions[K]?Z=this.defaultActions[K]:((X===null||typeof X>"u")&&(X=dt()),Z=$[K]&&$[K][X]),typeof Z>"u"||!Z.length||!Z[0]){var Lt="";Tt=[];for(ot in $[K])this.terminals_[ot]&&ot>Y&&Tt.push("'"+this.terminals_[ot]+"'");F.showPosition?Lt="Parse error on line "+(G+1)+`:
`+F.showPosition()+`
Expecting `+Tt.join(", ")+", got '"+(this.terminals_[X]||X)+"'":Lt="Parse error on line "+(G+1)+": Unexpected "+(X==A?"end of input":"'"+(this.terminals_[X]||X)+"'"),this.parseError(Lt,{text:F.match,token:this.terminals_[X]||X,line:F.yylineno,loc:at,expected:Tt})}if(Z[0]instanceof Array&&Z.length>1)throw new Error("Parse Error: multiple actions possible at state: "+K+", token: "+X);switch(Z[0]){case 1:y.push(X),C.push(F.yytext),s.push(F.yylloc),y.push(Z[1]),X=null,c=F.yyleng,o=F.yytext,G=F.yylineno,at=F.yylloc;break;case 2:if(tt=this.productions_[Z[1]][1],J.$=C[C.length-tt],J._$={first_line:s[s.length-(tt||1)].first_line,last_line:s[s.length-1].last_line,first_column:s[s.length-(tt||1)].first_column,last_column:s[s.length-1].last_column},ct&&(J._$.range=[s[s.length-(tt||1)].range[0],s[s.length-1].range[1]]),lt=this.performAction.apply(J,[o,c,G,q.yy,Z[1],C,s].concat(z)),typeof lt<"u")return lt;tt&&(y=y.slice(0,-1*tt*2),C=C.slice(0,-1*tt),s=s.slice(0,-1*tt)),y.push(this.productions_[Z[1]][0]),C.push(J.$),s.push(J._$),se=$[y[y.length-2]][y[y.length-1]],y.push(se);break;case 3:return!0}}return!0},"parse")},T=(function(){var p={EOF:1,parseError:l(function(d,y){if(this.yy.parser)this.yy.parser.parseError(d,y);else throw new Error(d)},"parseError"),setInput:l(function(a,d){return this.yy=d||this.yy||{},this._input=a,this._more=this._backtrack=this.done=!1,this.yylineno=this.yyleng=0,this.yytext=this.matched=this.match="",this.conditionStack=["INITIAL"],this.yylloc={first_line:1,first_column:0,last_line:1,last_column:0},this.options.ranges&&(this.yylloc.range=[0,0]),this.offset=0,this},"setInput"),input:l(function(){var a=this._input[0];this.yytext+=a,this.yyleng++,this.offset++,this.match+=a,this.matched+=a;var d=a.match(/(?:\r\n?|\n).*/g);return d?(this.yylineno++,this.yylloc.last_line++):this.yylloc.last_column++,this.options.ranges&&this.yylloc.range[1]++,this._input=this._input.slice(1),a},"input"),unput:l(function(a){var d=a.length,y=a.split(/(?:\r\n?|\n)/g);this._input=a+this._input,this.yytext=this.yytext.substr(0,this.yytext.length-d),this.offset-=d;var u=this.match.split(/(?:\r\n?|\n)/g);this.match=this.match.substr(0,this.match.length-1),this.matched=this.matched.substr(0,this.matched.length-1),y.length-1&&(this.yylineno-=y.length-1);var C=this.yylloc.range;return this.yylloc={first_line:this.yylloc.first_line,last_line:this.yylineno+1,first_column:this.yylloc.first_column,last_column:y?(y.length===u.length?this.yylloc.first_column:0)+u[u.length-y.length].length-y[0].length:this.yylloc.first_column-d},this.options.ranges&&(this.yylloc.range=[C[0],C[0]+this.yyleng-d]),this.yyleng=this.yytext.length,this},"unput"),more:l(function(){return this._more=!0,this},"more"),reject:l(function(){if(this.options.backtrack_lexer)this._backtrack=!0;else return this.parseError("Lexical error on line "+(this.yylineno+1)+`. You can only invoke reject() in the lexer when the lexer is of the backtracking persuasion (options.backtrack_lexer = true).
`+this.showPosition(),{text:"",token:null,line:this.yylineno});return this},"reject"),less:l(function(a){this.unput(this.match.slice(a))},"less"),pastInput:l(function(){var a=this.matched.substr(0,this.matched.length-this.match.length);return(a.length>20?"...":"")+a.substr(-20).replace(/\n/g,"")},"pastInput"),upcomingInput:l(function(){var a=this.match;return a.length<20&&(a+=this._input.substr(0,20-a.length)),(a.substr(0,20)+(a.length>20?"...":"")).replace(/\n/g,"")},"upcomingInput"),showPosition:l(function(){var a=this.pastInput(),d=new Array(a.length+1).join("-");return a+this.upcomingInput()+`
`+d+"^"},"showPosition"),test_match:l(function(a,d){var y,u,C;if(this.options.backtrack_lexer&&(C={yylineno:this.yylineno,yylloc:{first_line:this.yylloc.first_line,last_line:this.last_line,first_column:this.yylloc.first_column,last_column:this.yylloc.last_column},yytext:this.yytext,match:this.match,matches:this.matches,matched:this.matched,yyleng:this.yyleng,offset:this.offset,_more:this._more,_input:this._input,yy:this.yy,conditionStack:this.conditionStack.slice(0),done:this.done},this.options.ranges&&(C.yylloc.range=this.yylloc.range.slice(0))),u=a[0].match(/(?:\r\n?|\n).*/g),u&&(this.yylineno+=u.length),this.yylloc={first_line:this.yylloc.last_line,last_line:this.yylineno+1,first_column:this.yylloc.last_column,last_column:u?u[u.length-1].length-u[u.length-1].match(/\r?\n?/)[0].length:this.yylloc.last_column+a[0].length},this.yytext+=a[0],this.match+=a[0],this.matches=a,this.yyleng=this.yytext.length,this.options.ranges&&(this.yylloc.range=[this.offset,this.offset+=this.yyleng]),this._more=!1,this._backtrack=!1,this._input=this._input.slice(a[0].length),this.matched+=a[0],y=this.performAction.call(this,this.yy,this,d,this.conditionStack[this.conditionStack.length-1]),this.done&&this._input&&(this.done=!1),y)return y;if(this._backtrack){for(var s in C)this[s]=C[s];return!1}return!1},"test_match"),next:l(function(){if(this.done)return this.EOF;this._input||(this.done=!0);var a,d,y,u;this._more||(this.yytext="",this.match="");for(var C=this._currentRules(),s=0;s<C.length;s++)if(y=this._input.match(this.rules[C[s]]),y&&(!d||y[0].length>d[0].length)){if(d=y,u=s,this.options.backtrack_lexer){if(a=this.test_match(y,C[s]),a!==!1)return a;if(this._backtrack){d=!1;continue}else return!1}else if(!this.options.flex)break}return d?(a=this.test_match(d,C[u]),a!==!1?a:!1):this._input===""?this.EOF:this.parseError("Lexical error on line "+(this.yylineno+1)+`. Unrecognized text.
`+this.showPosition(),{text:"",token:null,line:this.yylineno})},"next"),lex:l(function(){var d=this.next();return d||this.lex()},"lex"),begin:l(function(d){this.conditionStack.push(d)},"begin"),popState:l(function(){var d=this.conditionStack.length-1;return d>0?this.conditionStack.pop():this.conditionStack[0]},"popState"),_currentRules:l(function(){return this.conditionStack.length&&this.conditionStack[this.conditionStack.length-1]?this.conditions[this.conditionStack[this.conditionStack.length-1]].rules:this.conditions.INITIAL.rules},"_currentRules"),topState:l(function(d){return d=this.conditionStack.length-1-Math.abs(d||0),d>=0?this.conditionStack[d]:"INITIAL"},"topState"),pushState:l(function(d){this.begin(d)},"pushState"),stateStackSize:l(function(){return this.conditionStack.length},"stateStackSize"),options:{"case-insensitive":!0},performAction:l(function(d,y,u,C){switch(u){case 0:return this.begin("open_directive"),"open_directive";case 1:return this.begin("acc_title"),31;case 2:return this.popState(),"acc_title_value";case 3:return this.begin("acc_descr"),33;case 4:return this.popState(),"acc_descr_value";case 5:this.begin("acc_descr_multiline");break;case 6:this.popState();break;case 7:return"acc_descr_multiline_value";case 8:break;case 9:break;case 10:break;case 11:return 10;case 12:break;case 13:break;case 14:this.begin("href");break;case 15:this.popState();break;case 16:return 43;case 17:this.begin("callbackname");break;case 18:this.popState();break;case 19:this.popState(),this.begin("callbackargs");break;case 20:return 41;case 21:this.popState();break;case 22:return 42;case 23:this.begin("click");break;case 24:this.popState();break;case 25:return 40;case 26:return 4;case 27:return 22;case 28:return 23;case 29:return 24;case 30:return 25;case 31:return 26;case 32:return 28;case 33:return 27;case 34:return 29;case 35:return 12;case 36:return 13;case 37:return 14;case 38:return 15;case 39:return 16;case 40:return 17;case 41:return 18;case 42:return 20;case 43:return 21;case 44:return"date";case 45:return 30;case 46:return"accDescription";case 47:return 36;case 48:return 38;case 49:return 39;case 50:return":";case 51:return 6;case 52:return"INVALID"}},"anonymous"),rules:[/^(?:%%\{)/i,/^(?:accTitle\s*:\s*)/i,/^(?:(?!\n||)*[^\n]*)/i,/^(?:accDescr\s*:\s*)/i,/^(?:(?!\n||)*[^\n]*)/i,/^(?:accDescr\s*\{\s*)/i,/^(?:[\}])/i,/^(?:[^\}]*)/i,/^(?:%%(?!\{)*[^\n]*)/i,/^(?:[^\}]%%*[^\n]*)/i,/^(?:%%*[^\n]*[\n]*)/i,/^(?:[\n]+)/i,/^(?:\s+)/i,/^(?:%[^\n]*)/i,/^(?:href[\s]+["])/i,/^(?:["])/i,/^(?:[^"]*)/i,/^(?:call[\s]+)/i,/^(?:\([\s]*\))/i,/^(?:\()/i,/^(?:[^(]*)/i,/^(?:\))/i,/^(?:[^)]*)/i,/^(?:click[\s]+)/i,/^(?:[\s\n])/i,/^(?:[^\s\n]*)/i,/^(?:gantt\b)/i,/^(?:dateFormat\s[^#\n;]+)/i,/^(?:inclusiveEndDates\b)/i,/^(?:topAxis\b)/i,/^(?:axisFormat\s[^#\n;]+)/i,/^(?:tickInterval\s[^#\n;]+)/i,/^(?:includes\s[^#\n;]+)/i,/^(?:excludes\s[^#\n;]+)/i,/^(?:todayMarker\s[^\n;]+)/i,/^(?:weekday\s+monday\b)/i,/^(?:weekday\s+tuesday\b)/i,/^(?:weekday\s+wednesday\b)/i,/^(?:weekday\s+thursday\b)/i,/^(?:weekday\s+friday\b)/i,/^(?:weekday\s+saturday\b)/i,/^(?:weekday\s+sunday\b)/i,/^(?:weekend\s+friday\b)/i,/^(?:weekend\s+saturday\b)/i,/^(?:\d\d\d\d-\d\d-\d\d\b)/i,/^(?:title\s[^\n]+)/i,/^(?:accDescription\s[^#\n;]+)/i,/^(?:section\s[^\n]+)/i,/^(?:[^:\n]+)/i,/^(?::[^#\n;]+)/i,/^(?::)/i,/^(?:$)/i,/^(?:.)/i],conditions:{acc_descr_multiline:{rules:[6,7],inclusive:!1},acc_descr:{rules:[4],inclusive:!1},acc_title:{rules:[2],inclusive:!1},callbackargs:{rules:[21,22],inclusive:!1},callbackname:{rules:[18,19,20],inclusive:!1},href:{rules:[15,16],inclusive:!1},click:{rules:[24,25],inclusive:!1},INITIAL:{rules:[0,1,3,5,8,9,10,11,12,13,14,17,23,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52],inclusive:!0}}};return p})();h.lexer=T;function v(){this.yy={}}return l(v,"Parser"),v.prototype=h,h.Parser=v,new v})();qt.parser=qt;var qn=qt;U.extend(Yn);U.extend(On);U.extend(Vn);var pe={friday:5,saturday:6},et="",Ut="",Zt=void 0,Qt="",yt=[],gt=[],Kt=new Map,Jt=[],Yt=[],pt="",te="",Ae=["active","done","crit","milestone","vert"],ee=[],ft="",xt=!1,ne=!1,re="sunday",At="saturday",Gt=0,Gn=l(function(){Jt=[],Yt=[],pt="",ee=[],Et=0,jt=void 0,It=void 0,j=[],et="",Ut="",te="",Zt=void 0,Qt="",yt=[],gt=[],xt=!1,ne=!1,Gt=0,Kt=new Map,ft="",Ke(),re="sunday",At="saturday"},"clear"),Xn=l(function(t){ft=t},"setDiagramId"),jn=l(function(t){Ut=t},"setAxisFormat"),Un=l(function(){return Ut},"getAxisFormat"),Zn=l(function(t){Zt=t},"setTickInterval"),Qn=l(function(){return Zt},"getTickInterval"),Kn=l(function(t){Qt=t},"setTodayMarker"),Jn=l(function(){return Qt},"getTodayMarker"),tr=l(function(t){et=t},"setDateFormat"),er=l(function(){xt=!0},"enableInclusiveEndDates"),nr=l(function(){return xt},"endDatesAreInclusive"),rr=l(function(){ne=!0},"enableTopAxis"),ir=l(function(){return ne},"topAxisEnabled"),sr=l(function(t){te=t},"setDisplayMode"),ar=l(function(){return te},"getDisplayMode"),or=l(function(){return et},"getDateFormat"),Fe=l((t,e)=>{const n=e.toLowerCase().split(/[\s,]+/).filter(r=>r!=="");return[...new Set([...t,...n])]},"mergeTokens"),cr=l(function(t){yt=Fe(yt,t)},"setIncludes"),lr=l(function(){return yt},"getIncludes"),ur=l(function(t){gt=Fe(gt,t)},"setExcludes"),dr=l(function(){return gt},"getExcludes"),fr=l(function(){return Kt},"getLinks"),hr=l(function(t){pt=t,Jt.push(t)},"addSection"),mr=l(function(){return Jt},"getSections"),kr=l(function(){let t=ve();const e=10;let n=0;for(;!t&&n<e;)t=ve(),n++;return Yt=j,Yt},"getTasks"),Le=l(function(t,e,n,r){const i=t.format(e.trim()),m=t.format("YYYY-MM-DD");return r.includes(i)||r.includes(m)?!1:n.includes("weekends")&&(t.isoWeekday()===pe[At]||t.isoWeekday()===pe[At]+1)||n.includes(t.format("dddd").toLowerCase())?!0:n.includes(i)||n.includes(m)},"isInvalidDate"),yr=l(function(t){re=t},"setWeekday"),gr=l(function(){return re},"getWeekday"),pr=l(function(t){At=t},"setWeekend"),Oe=l(function(t,e,n,r){if(!n.length||t.manualEndTime)return;let i;t.startTime instanceof Date?i=U(t.startTime):i=U(t.startTime,e,!0),i=i.add(1,"d");let m;t.endTime instanceof Date?m=U(t.endTime):m=U(t.endTime,e,!0);const[f,b]=vr(i,m,e,n,r);t.endTime=f.toDate(),t.renderEndTime=b},"checkTaskDates"),vr=l(function(t,e,n,r,i){let m=!1,f=null;const b=e.add(1e4,"d");for(;t<=e;){if(m||(f=e.toDate()),m=Le(t,n,r,i),m&&(e=e.add(1,"d"),e>b))throw new Error("Failed to find a valid date that was not excluded by `excludes` after 10,000 iterations.");t=t.add(1,"d")}return[e,f]},"fixTaskDates"),We=l(function(t,e){it.warn(`Gantt: the "${t}" statement references unknown task id(s): ${e.join(", ")}. Make sure the referenced tasks exist and declare an id. Milestones need both an id and a duration, e.g. "Milestone :milestone, m1, 2023-01-01, 0d".`)},"warnAboutUnknownTaskIds"),Xt=l(function(t,e,n){if(n=n.trim(),l(b=>{const S=b.trim();return S==="x"||S==="X"},"isTimestampFormat")(e)&&/^\d+$/.test(n))return new Date(Number(n));const m=/^after\s+(?<ids>[\d\w- ]+)/.exec(n);if(m!==null){let b=null;const S=[],L=m.groups.ids.split(" ").filter(W=>W!=="");for(const W of L){const w=ut(W);if(w===void 0){S.push(W);continue}(!b||w.endTime>b.endTime)&&(b=w)}if(S.length>0&&We("after",S),b)return b.endTime;const _=new Date;return _.setHours(0,0,0,0),_}let f=U(n,e.trim(),!0);if(f.isValid())return f.toDate();{it.debug("Invalid date:"+n),it.debug("With date format:"+e.trim());const b=new Date(n);if(b===void 0||isNaN(b.getTime())||b.getFullYear()<-1e4||b.getFullYear()>1e4)throw new Error("Invalid date:"+n);return b}},"getStartDate"),Ne=l(function(t){const e=/^(\d+(?:\.\d+)?)([Mdhmswy]|ms)$/.exec(t.trim());return e!==null?[Number.parseFloat(e[1]),e[2]]:[NaN,"ms"]},"parseDuration"),Pe=l(function(t,e,n,r=!1){n=n.trim();const m=/^until\s+(?<ids>[\d\w- ]+)/.exec(n);if(m!==null){let _=null;const W=[],w=m.groups.ids.split(" ").filter(R=>R!=="");for(const R of w){const P=ut(R);if(P===void 0){W.push(R);continue}(!_||P.startTime<_.startTime)&&(_=P)}if(W.length>0&&We("until",W),_)return _.startTime;const D=new Date;return D.setHours(0,0,0,0),D}let f=U(n,e.trim(),!0);if(f.isValid())return r&&(f=f.add(1,"d")),f.toDate();let b=U(t);const[S,L]=Ne(n);if(Number.isNaN(S))it.warn(`Gantt: "${n}" is neither a valid date for the "${e.trim()}" date format nor a valid duration (e.g. "3d"), so it is ignored and the task gets a zero duration. Milestones need a duration too, e.g. "Milestone :milestone, m1, 2023-01-01, 0d".`);else{const _=b.add(S,L);_.isValid()&&(b=_)}return b.toDate()},"getEndDate"),Et=0,kt=l(function(t){return t===void 0?(Et=Et+1,"task"+Et):t},"parseId"),xr=l(function(t,e){let n;e.substr(0,1)===":"?n=e.substr(1,e.length):n=e;const r=n.split(","),i={};ie(r,i,Ae);for(let f=0;f<r.length;f++)r[f]=r[f].trim();let m="";switch(r.length){case 1:i.id=kt(),i.startTime=t.endTime,m=r[0];break;case 2:i.id=kt(),i.startTime=Xt(void 0,et,r[0]),m=r[1];break;case 3:i.id=kt(r[0]),i.startTime=Xt(void 0,et,r[1]),m=r[2];break}return m&&(i.endTime=Pe(i.startTime,et,m,xt),i.manualEndTime=U(m,"YYYY-MM-DD",!0).isValid(),Oe(i,et,gt,yt)),i},"compileData"),Tr=l(function(t,e){let n;e.substr(0,1)===":"?n=e.substr(1,e.length):n=e;const r=n.split(","),i={};ie(r,i,Ae);for(let m=0;m<r.length;m++)r[m]=r[m].trim();switch(r.length){case 1:i.id=kt(),i.startTime={type:"prevTaskEnd",id:t},i.endTime={data:r[0]};break;case 2:i.id=kt(),i.startTime={type:"getStartDate",startData:r[0]},i.endTime={data:r[1]};break;case 3:i.id=kt(r[0]),i.startTime={type:"getStartDate",startData:r[1]},i.endTime={data:r[2]};break}return i},"parseData"),jt,It,j=[],Ve={},br=l(function(t,e){const n={section:pt,type:pt,processed:!1,manualEndTime:!1,renderEndTime:null,raw:{data:e},task:t,classes:[]},r=Tr(It,e);n.raw.startTime=r.startTime,n.raw.endTime=r.endTime,n.id=r.id,n.prevTaskId=It,n.active=r.active,n.done=r.done,n.crit=r.crit,n.milestone=r.milestone,n.vert=r.vert,n.vert?n.order=-1:(n.order=Gt,Gt++);const i=j.push(n);It=n.id,Ve[n.id]=i-1},"addTask"),ut=l(function(t){const e=Ve[t];return j[e]},"findTaskById"),wr=l(function(t,e){const n={section:pt,type:pt,description:t,task:t,classes:[]},r=xr(jt,e);n.startTime=r.startTime,n.endTime=r.endTime,n.id=r.id,n.active=r.active,n.done=r.done,n.crit=r.crit,n.milestone=r.milestone,n.vert=r.vert,jt=n,Yt.push(n)},"addTaskOrg"),ve=l(function(){const t=l(function(n){const r=j[n];let i="";switch(j[n].raw.startTime.type){case"prevTaskEnd":{const m=ut(r.prevTaskId);r.startTime=m.endTime;break}case"getStartDate":i=Xt(void 0,et,j[n].raw.startTime.startData),i&&(j[n].startTime=i);break}return j[n].startTime&&(j[n].endTime=Pe(j[n].startTime,et,j[n].raw.endTime.data,xt),j[n].endTime&&(j[n].processed=!0,j[n].manualEndTime=U(j[n].raw.endTime.data,"YYYY-MM-DD",!0).isValid(),Oe(j[n],et,gt,yt))),j[n].processed},"compileTask");let e=!0;for(const[n,r]of j.entries())t(n),e=e&&r.processed;return e},"compileTasks"),_r=l(function(t,e){let n=e;ht().securityLevel!=="loose"&&(n=Qe.sanitizeUrl(e)),t.split(",").forEach(function(r){ut(r)!==void 0&&(Re(r,()=>{window.open(n,"_self")}),Kt.set(r,n))}),ze(t,"clickable")},"setLink"),ze=l(function(t,e){t.split(",").forEach(function(n){let r=ut(n);r!==void 0&&r.classes.push(e)})},"setClass"),Dr=l(function(t,e,n){if(ht().securityLevel!=="loose"||e===void 0)return;let r=[];if(typeof n=="string"){r=n.split(/,(?=(?:(?:[^"]*"){2})*[^"]*$)/);for(let m=0;m<r.length;m++){let f=r[m].trim();f.startsWith('"')&&f.endsWith('"')&&(f=f.substr(1,f.length-2)),r[m]=f}}r.length===0&&r.push(t),ut(t)!==void 0&&Re(t,()=>{Je.runFunc(e,...r)})},"setClickFun"),Re=l(function(t,e){ee.push(function(){const n=ft?`${ft}-${t}`:t,r=document.querySelector(`[id="${n}"]`);r!==null&&r.addEventListener("click",function(){e()})},function(){const n=ft?`${ft}-${t}`:t,r=document.querySelector(`[id="${n}-text"]`);r!==null&&r.addEventListener("click",function(){e()})})},"pushFun"),Sr=l(function(t,e,n){t.split(",").forEach(function(r){Dr(r,e,n)}),ze(t,"clickable")},"setClickEvent"),Cr=l(function(t){ee.forEach(function(e){e(t)})},"bindFunctions"),Mr={getConfig:l(()=>ht().gantt,"getConfig"),clear:Gn,setDateFormat:tr,getDateFormat:or,enableInclusiveEndDates:er,endDatesAreInclusive:nr,enableTopAxis:rr,topAxisEnabled:ir,setAxisFormat:jn,getAxisFormat:Un,setTickInterval:Zn,getTickInterval:Qn,setTodayMarker:Kn,getTodayMarker:Jn,setAccTitle:je,getAccTitle:Xe,setDiagramTitle:Ge,getDiagramTitle:qe,setDiagramId:Xn,setDisplayMode:sr,getDisplayMode:ar,setAccDescription:Be,getAccDescription:He,addSection:hr,getSections:mr,getTasks:kr,addTask:br,findTaskById:ut,addTaskOrg:wr,setIncludes:cr,getIncludes:lr,setExcludes:ur,getExcludes:dr,setClickEvent:Sr,setLink:_r,getLinks:fr,bindFunctions:Cr,parseDuration:Ne,isInvalidDate:Le,setWeekday:yr,getWeekday:gr,setWeekend:pr};function ie(t,e,n){let r=!0;for(;r;)r=!1,n.forEach(function(i){const m="^\\s*"+i+"\\s*$",f=new RegExp(m);t[0].match(f)&&(e[i]=!0,t.shift(1),r=!0)})}l(ie,"getTaskTags");U.extend(Bn);var Er=l(function(){it.debug("Something is calling, setConf, remove the call")},"setConf"),xe={monday:un,tuesday:ln,wednesday:cn,thursday:on,friday:an,saturday:sn,sunday:rn},Ir=l((t,e)=>{let n=[...t].map(()=>-1/0),r=[...t].sort((m,f)=>m.startTime-f.startTime||m.order-f.order),i=0;for(const m of r)for(let f=0;f<n.length;f++)if(m.startTime>=n[f]){n[f]=m.endTime,m.order=f+e,f>i&&(i=f);break}return i},"getMaxIntersections"),rt,Rt=1e4,$r=l(function(t,e,n,r){const i=ht().gantt;r.db.setDiagramId(e);const m=ht().securityLevel;let f;m==="sandbox"&&(f=bt("#i"+e));const b=m==="sandbox"?bt(f.nodes()[0].contentDocument.body):bt("body"),S=m==="sandbox"?f.nodes()[0].contentDocument:document,L=S.getElementById(e);rt=L.parentElement.offsetWidth,rt===void 0&&(rt=1200),i.useWidth!==void 0&&(rt=i.useWidth);const _=r.db.getTasks(),W=_.filter(h=>!h.vert);let w=[];for(const h of W)w.push(h.type);w=E(w);const D={};let R=2*i.topPadding;if(r.db.getDisplayMode()==="compact"||i.displayMode==="compact"){const h={};for(const v of W)h[v.section]===void 0?h[v.section]=[v]:h[v.section].push(v);let T=0;for(const v of Object.keys(h)){const p=Ir(h[v],T)+1;T+=p,R+=p*(i.barHeight+i.barGap),D[v]=p}}else{R+=W.length*(i.barHeight+i.barGap);for(const h of w)D[h]=W.filter(T=>T.type===h).length}L.setAttribute("viewBox","0 0 "+rt+" "+R);const P=b.select(`[id="${e}"]`),g=nn().domain([xn(_,function(h){return h.startTime}),vn(_,function(h){return h.endTime})]).rangeRound([0,rt-i.leftPadding-i.rightPadding]);function M(h,T){const v=h.startTime,p=T.startTime;let a=0;return v>p?a=1:v<p&&(a=-1),a}l(M,"taskCompare"),_.sort(M),N(_,rt,R),Ue(P,R,rt,i.useMaxWidth),P.append("text").text(r.db.getDiagramTitle()).attr("x",rt/2).attr("y",i.titleTopMargin).attr("class","titleText");function N(h,T,v){const p=i.barHeight,a=p+i.barGap,d=i.topPadding,y=i.leftPadding,u=dn().domain([0,w.length]).range(["#00B9FA","#F95002"]).interpolate(pn);B(a,d,y,T,v,h,r.db.getExcludes(),r.db.getIncludes()),I(y,d,T,v),O(h,a,d,y,p,u,T),x(a,d),k(y,d,T,v)}l(N,"makeGantt");function O(h,T,v,p,a,d,y){h.sort((c,Y)=>c.vert===Y.vert?0:c.vert?1:-1);const u=h.filter(c=>!c.vert),s=[...new Set(u.map(c=>c.order))].map(c=>u.find(Y=>Y.order===c));P.append("g").selectAll("rect").data(s).enter().append("rect").attr("x",0).attr("y",function(c,Y){return Y=c.order,Y*T+v-2}).attr("width",function(){return y-i.rightPadding/2}).attr("height",T).attr("class",function(c){for(const[Y,A]of w.entries())if(c.type===A)return"section section"+Y%i.numberSectionStyles;return"section section0"}).enter();const $=P.append("g").selectAll("rect").data(h).enter(),o=r.db.getLinks();if($.append("rect").attr("id",function(c){return e+"-"+c.id}).attr("rx",3).attr("ry",3).attr("x",function(c){return c.milestone?g(c.startTime)+p+.5*(g(c.endTime)-g(c.startTime))-.5*a:g(c.startTime)+p}).attr("y",function(c,Y){return Y=c.order,c.vert?i.gridLineStartPadding:Y*T+v}).attr("width",function(c){return c.milestone?a:c.vert?.08*a:g(c.renderEndTime||c.endTime)-g(c.startTime)}).attr("height",function(c){return c.vert?u.length*(i.barHeight+i.barGap)+i.barHeight*2:a}).attr("transform-origin",function(c,Y){return Y=c.order,(g(c.startTime)+p+.5*(g(c.endTime)-g(c.startTime))).toString()+"px "+(Y*T+v+.5*a).toString()+"px"}).attr("class",function(c){const Y="task";let A="";c.classes.length>0&&(A=c.classes.join(" "));let z=0;for(const[q,V]of w.entries())c.type===V&&(z=q%i.numberSectionStyles);let F="";return c.active?c.crit?F+=" activeCrit":F=" active":c.done?c.crit?F=" doneCrit":F=" done":c.crit&&(F+=" crit"),F.length===0&&(F=" task"),c.milestone&&(F=" milestone "+F),c.vert&&(F=" vert "+F),F+=z,F+=" "+A,Y+F}),$.append("text").attr("id",function(c){return e+"-"+c.id+"-text"}).text(function(c){return c.task}).attr("font-size",i.fontSize).attr("x",function(c){let Y=g(c.startTime),A=g(c.renderEndTime||c.endTime);if(c.milestone&&(Y+=.5*(g(c.endTime)-g(c.startTime))-.5*a,A=Y+a),c.vert)return g(c.startTime)+p;const z=this.getBBox().width;return z>A-Y?A+z+1.5*i.leftPadding>y?Y+p-5:A+p+5:(A-Y)/2+Y+p}).attr("y",function(c,Y){return c.vert?i.gridLineStartPadding+u.length*(i.barHeight+i.barGap)+60:(Y=c.order,Y*T+i.barHeight/2+(i.fontSize/2-2)+v)}).attr("text-height",a).attr("class",function(c){const Y=g(c.startTime);let A=g(c.endTime);c.milestone&&(A=Y+a);const z=this.getBBox().width;let F="";c.classes.length>0&&(F=c.classes.join(" "));let q=0;for(const[at,ct]of w.entries())c.type===ct&&(q=at%i.numberSectionStyles);let V="";return c.active&&(c.crit?V="activeCritText"+q:V="activeText"+q),c.done?c.crit?V=V+" doneCritText"+q:V=V+" doneText"+q:c.crit&&(V=V+" critText"+q),c.milestone&&(V+=" milestoneText"),c.vert&&(V+=" vertText"),z>A-Y?A+z+1.5*i.leftPadding>y?F+" taskTextOutsideLeft taskTextOutside"+q+" "+V:F+" taskTextOutsideRight taskTextOutside"+q+" "+V+" width-"+z:F+" taskText taskText"+q+" "+V+" width-"+z}),ht().securityLevel==="sandbox"){let c;c=bt("#i"+e);const Y=c.nodes()[0].contentDocument;$.filter(function(A){return o.has(A.id)}).each(function(A){var z=Y.querySelector("#"+CSS.escape(e+"-"+A.id)),F=Y.querySelector("#"+CSS.escape(e+"-"+A.id+"-text"));const q=z.parentNode;var V=Y.createElement("a");V.setAttribute("xlink:href",o.get(A.id)),V.setAttribute("target","_top"),q.appendChild(V),V.appendChild(z),V.appendChild(F)})}}l(O,"drawRects");function B(h,T,v,p,a,d,y,u){if(y.length===0&&u.length===0)return;let C,s;for(const{startTime:A,endTime:z}of d)(C===void 0||A<C)&&(C=A),(s===void 0||z>s)&&(s=z);if(!C||!s)return;if(U(s).diff(U(C),"year")>5){it.warn("The difference between the min and max time is more than 5 years. This will cause performance issues. Skipping drawing exclude days.");return}const $=r.db.getDateFormat(),o=[];let G=null,c=U(C);for(;c.valueOf()<=s;)r.db.isInvalidDate(c,$,y,u)?G?G.end=c:G={start:c,end:c}:G&&(o.push(G),G=null),c=c.add(1,"d");P.append("g").selectAll("rect").data(o).enter().append("rect").attr("id",A=>e+"-exclude-"+A.start.format("YYYY-MM-DD")).attr("x",A=>g(A.start.startOf("day"))+v).attr("y",i.gridLineStartPadding).attr("width",A=>g(A.end.endOf("day"))-g(A.start.startOf("day"))).attr("height",a-T-i.gridLineStartPadding).attr("transform-origin",function(A,z){return(g(A.start)+v+.5*(g(A.end)-g(A.start))).toString()+"px "+(z*h+.5*a).toString()+"px"}).attr("class","exclude-range")}l(B,"drawExcludeDays");function H(h,T,v,p){if(v<=0||h>T)return 1/0;const a=T-h,d=U.duration({[p??"day"]:v}).asMilliseconds();return d<=0?1/0:Math.ceil(a/d)}l(H,"getEstimatedTickCount");function I(h,T,v,p){const a=r.db.getDateFormat(),d=r.db.getAxisFormat();let y;d?y=d:a==="D"?y="%d":y=i.axisFormat??"%Y-%m-%d";let u=Mn(g).tickSize(-p+T+i.gridLineStartPadding).tickFormat(ae(y));const s=/^([1-9]\d*)(millisecond|second|minute|hour|day|week|month)$/.exec(r.db.getTickInterval()||i.tickInterval);if(s!==null){const $=parseInt(s[1],10);if(isNaN($)||$<=0)it.warn(`Invalid tick interval value: "${s[1]}". Skipping custom tick interval.`);else{const o=s[2],G=r.db.getWeekday()||i.weekday,c=g.domain(),Y=c[0],A=c[1],z=H(Y,A,$,o);if(z>Rt)it.warn(`The tick interval "${$}${o}" would generate ${z} ticks, which exceeds the maximum allowed (${Rt}). This may indicate an invalid date or time range. Skipping custom tick interval.`);else switch(o){case"millisecond":u.ticks(fe.every($));break;case"second":u.ticks(de.every($));break;case"minute":u.ticks(ue.every($));break;case"hour":u.ticks(le.every($));break;case"day":u.ticks(ce.every($));break;case"week":u.ticks(xe[G].every($));break;case"month":u.ticks(oe.every($));break}}}if(P.append("g").attr("class","grid").attr("transform","translate("+h+", "+(p-50)+")").call(u).selectAll("text").style("text-anchor","middle").attr("fill","#000").attr("stroke","none").attr("font-size",10).attr("dy","1em"),r.db.topAxisEnabled()||i.topAxis){let $=Cn(g).tickSize(-p+T+i.gridLineStartPadding).tickFormat(ae(y));if(s!==null){const o=parseInt(s[1],10);if(isNaN(o)||o<=0)it.warn(`Invalid tick interval value: "${s[1]}". Skipping custom tick interval.`);else{const G=s[2],c=r.db.getWeekday()||i.weekday,Y=g.domain(),A=Y[0],z=Y[1];if(H(A,z,o,G)<=Rt)switch(G){case"millisecond":$.ticks(fe.every(o));break;case"second":$.ticks(de.every(o));break;case"minute":$.ticks(ue.every(o));break;case"hour":$.ticks(le.every(o));break;case"day":$.ticks(ce.every(o));break;case"week":$.ticks(xe[c].every(o));break;case"month":$.ticks(oe.every(o));break}}}P.append("g").attr("class","grid").attr("transform","translate("+h+", "+T+")").call($).selectAll("text").style("text-anchor","middle").attr("fill","#000").attr("stroke","none").attr("font-size",10)}}l(I,"makeGrid");function x(h,T){let v=0;const p=Object.keys(D).map(a=>[a,D[a]]);P.append("g").selectAll("text").data(p).enter().append(function(a){const d=a[0].split(Ze.lineBreakRegex),y=-(d.length-1)/2,u=S.createElementNS("http://www.w3.org/2000/svg","text");u.setAttribute("dy",y+"em");for(const[C,s]of d.entries()){const $=S.createElementNS("http://www.w3.org/2000/svg","tspan");$.setAttribute("alignment-baseline","central"),$.setAttribute("x","10"),C>0&&$.setAttribute("dy","1em"),$.textContent=s,u.appendChild($)}return u}).attr("x",10).attr("y",function(a,d){if(d>0)for(let y=0;y<d;y++)return v+=p[d-1][1],a[1]*h/2+v*h+T;else return a[1]*h/2+T}).attr("font-size",i.sectionFontSize).attr("class",function(a){for(const[d,y]of w.entries())if(a[0]===y)return"sectionTitle sectionTitle"+d%i.numberSectionStyles;return"sectionTitle"})}l(x,"vertLabels");function k(h,T,v,p){const a=r.db.getTodayMarker();if(a==="off")return;const d=P.append("g").attr("class","today"),y=new Date,u=d.append("line");u.attr("x1",g(y)+h).attr("x2",g(y)+h).attr("y1",i.titleTopMargin).attr("y2",p-i.titleTopMargin).attr("class","today"),a!==""&&u.attr("style",a.replace(/,/g,";"))}l(k,"drawToday");function E(h){const T={},v=[];for(let p=0,a=h.length;p<a;++p)Object.prototype.hasOwnProperty.call(T,h[p])||(T[h[p]]=!0,v.push(h[p]));return v}l(E,"checkUnique")},"draw"),Yr={setConf:Er,draw:$r},Ar=l(t=>`
  .mermaid-main-font {
        font-family: ${t.fontFamily};
  }

  .exclude-range {
    fill: ${t.excludeBkgColor};
  }

  .section {
    stroke: none;
    opacity: 0.2;
  }

  .section0 {
    fill: ${t.sectionBkgColor};
  }

  .section2 {
    fill: ${t.sectionBkgColor2};
  }

  .section1,
  .section3 {
    fill: ${t.altSectionBkgColor};
    opacity: 0.2;
  }

  .sectionTitle0 {
    fill: ${t.titleColor};
  }

  .sectionTitle1 {
    fill: ${t.titleColor};
  }

  .sectionTitle2 {
    fill: ${t.titleColor};
  }

  .sectionTitle3 {
    fill: ${t.titleColor};
  }

  .sectionTitle {
    text-anchor: start;
    font-family: ${t.fontFamily};
  }


  /* Grid and axis */

  .grid .tick {
    stroke: ${t.gridColor};
    opacity: 0.8;
    shape-rendering: crispEdges;
  }

  .grid .tick text {
    font-family: ${t.fontFamily};
    fill: ${t.textColor};
  }

  .grid path {
    stroke-width: 0;
  }


  /* Today line */

  .today {
    fill: none;
    stroke: ${t.todayLineColor};
    stroke-width: 2px;
  }


  /* Task styling */

  /* Default task */

  .task {
    stroke-width: 2;
  }

  .taskText {
    text-anchor: middle;
    font-family: ${t.fontFamily};
  }

  .taskTextOutsideRight {
    fill: ${t.taskTextDarkColor};
    text-anchor: start;
    font-family: ${t.fontFamily};
  }

  .taskTextOutsideLeft {
    fill: ${t.taskTextDarkColor};
    text-anchor: end;
  }


  /* Special case clickable */

  .task.clickable {
    cursor: pointer;
  }

  .taskText.clickable {
    cursor: pointer;
    fill: ${t.taskTextClickableColor} !important;
    font-weight: bold;
  }

  .taskTextOutsideLeft.clickable {
    cursor: pointer;
    fill: ${t.taskTextClickableColor} !important;
    font-weight: bold;
  }

  .taskTextOutsideRight.clickable {
    cursor: pointer;
    fill: ${t.taskTextClickableColor} !important;
    font-weight: bold;
  }


  /* Specific task settings for the sections*/

  .taskText0,
  .taskText1,
  .taskText2,
  .taskText3 {
    fill: ${t.taskTextColor};
  }

  .task0,
  .task1,
  .task2,
  .task3 {
    fill: ${t.taskBkgColor};
    stroke: ${t.taskBorderColor};
  }

  .taskTextOutside0,
  .taskTextOutside2
  {
    fill: ${t.taskTextOutsideColor};
  }

  .taskTextOutside1,
  .taskTextOutside3 {
    fill: ${t.taskTextOutsideColor};
  }


  /* Active task */

  .active0,
  .active1,
  .active2,
  .active3 {
    fill: ${t.activeTaskBkgColor};
    stroke: ${t.activeTaskBorderColor};
  }

  .activeText0,
  .activeText1,
  .activeText2,
  .activeText3 {
    fill: ${t.taskTextDarkColor} !important;
  }


  /* Completed task */

  .done0,
  .done1,
  .done2,
  .done3 {
    stroke: ${t.doneTaskBorderColor};
    fill: ${t.doneTaskBkgColor};
    stroke-width: 2;
  }

  .doneText0,
  .doneText1,
  .doneText2,
  .doneText3 {
    fill: ${t.taskTextDarkColor} !important;
  }

  /* Done task text displayed outside the bar sits against the diagram background,
     not against the done-task bar, so it must use the outside/contrast color. */
  .doneText0.taskTextOutsideLeft,
  .doneText0.taskTextOutsideRight,
  .doneText1.taskTextOutsideLeft,
  .doneText1.taskTextOutsideRight,
  .doneText2.taskTextOutsideLeft,
  .doneText2.taskTextOutsideRight,
  .doneText3.taskTextOutsideLeft,
  .doneText3.taskTextOutsideRight {
    fill: ${t.taskTextOutsideColor} !important;
  }


  /* Tasks on the critical line */

  .crit0,
  .crit1,
  .crit2,
  .crit3 {
    stroke: ${t.critBorderColor};
    fill: ${t.critBkgColor};
    stroke-width: 2;
  }

  .activeCrit0,
  .activeCrit1,
  .activeCrit2,
  .activeCrit3 {
    stroke: ${t.critBorderColor};
    fill: ${t.activeTaskBkgColor};
    stroke-width: 2;
  }

  .doneCrit0,
  .doneCrit1,
  .doneCrit2,
  .doneCrit3 {
    stroke: ${t.critBorderColor};
    fill: ${t.doneTaskBkgColor};
    stroke-width: 2;
    cursor: pointer;
    shape-rendering: crispEdges;
  }

  .milestone {
    transform: rotate(45deg) scale(0.8,0.8);
  }

  .milestoneText {
    font-style: italic;
  }
  .doneCritText0,
  .doneCritText1,
  .doneCritText2,
  .doneCritText3 {
    fill: ${t.taskTextDarkColor} !important;
  }

  /* Done-crit task text outside the bar — same reasoning as doneText above. */
  .doneCritText0.taskTextOutsideLeft,
  .doneCritText0.taskTextOutsideRight,
  .doneCritText1.taskTextOutsideLeft,
  .doneCritText1.taskTextOutsideRight,
  .doneCritText2.taskTextOutsideLeft,
  .doneCritText2.taskTextOutsideRight,
  .doneCritText3.taskTextOutsideLeft,
  .doneCritText3.taskTextOutsideRight {
    fill: ${t.taskTextOutsideColor} !important;
  }

  .vert {
    stroke: ${t.vertLineColor};
  }

  .vertText {
    font-size: 15px;
    text-anchor: middle;
    fill: ${t.vertLineColor} !important;
  }

  .activeCritText0,
  .activeCritText1,
  .activeCritText2,
  .activeCritText3 {
    fill: ${t.taskTextDarkColor} !important;
  }

  .titleText {
    text-anchor: middle;
    font-size: 18px;
    fill: ${t.titleColor||t.textColor};
    font-family: ${t.fontFamily};
  }
`,"getStyles"),Fr=Ar,Br={parser:qn,db:Mr,renderer:Yr,styles:Fr};export{Br as diagram};
