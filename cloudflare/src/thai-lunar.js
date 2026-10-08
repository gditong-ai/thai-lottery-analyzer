// Thai lunisolar Chulasakarat calendar, JavaScript port of KranaxALT/thailunar
// (MIT, based on Mark Hollow's pythaidate, MIT).
// Copyright 2023 Mark Hollow. Original algorithm: https://github.com/hmmbug/pythaidate
const mod=(a,b)=>(a%b+b)%b;
function yearBase(year){
 const hk=Math.floor((year*292207+373)/800)+1;
 const kam=800-mod(year*292207+373,800);
 const q=Math.floor((hk*11+650)/692);
 let avo=mod(hk*11+650,692);if(!avo)avo=692;
 let tithi=mod(q+hk,30);if(avo===692)tithi--;
 const hk1=Math.floor(((year+1)*292207+373)/800)+1;
 const tithi1=mod(Math.floor((hk1*11+650)/692)+hk1,30);
 let langsak=Math.max(1,tithi), n=langsak;if(n<6)n+=29;
 let nyd=mod(mod(hk,7)-n+1+35,7);
 const leapday=kam<=207;
 let type=tithi>24||tithi<6?'C':'A';
 if(tithi===25&&tithi1===5)type='A';
 if((leapday&&avo<=126)||(!leapday&&avo<=137))type=type==='C'?'c':'B';
 return {hk,tithi,langsak,nyd,leapday,type,offset:false,nextNyd:mod(nyd+({A:4,B:5,C:6,c:6}[type]),7)};
}
function lunarYear(year){
 const ys=Array.from({length:5},(_,i)=>yearBase(year+i-2));
 if(ys[2].tithi===24&&ys[3].tithi===6)for(const y of ys){y.type='C';y.nextNyd=mod(y.nextNyd+2,7);}
 for(let i=1;i<=3;i++)if(ys[i].type==='c'){const j=ys[i].nyd===ys[i-1].nextNyd?1:-1;ys[i+j].type='B';ys[i+j].nextNyd=mod(ys[i+j].nextNyd+1,7);}
 for(let i=1;i<=3;i++)if(ys[i-1].nextNyd!==ys[i].nyd&&ys[i].nextNyd!==ys[i+1].nyd){ys[i].offset=true;ys[i].langsak++;ys[i].nyd=mod(ys[i].nyd+6,7);ys[i].nextNyd=mod(ys[i].nextNyd+6,7);}
 const y=ys[2];if(y.type==='c')y.type='C';
 y.offsetDays=y.langsak;if(y.offsetDays<6+(y.offset?1:0))y.offsetDays+=29;
 return y;
}
const boundaries={
 A:[[383,16],[354,15],[324,12],[295,11],[265,10],[236,9],[206,8],[177,7],[147,6],[118,5],[88,4],[59,3],[29,2]],
 B:[[384,16],[355,15],[325,12],[296,11],[266,10],[237,9],[207,8],[178,7],[148,6],[119,5],[89,4],[59,3],[29,2]],
 C:[[384,15],[354,12],[325,11],[295,10],[266,9],[236,8],[207,7],[177,6],[148,5],[118,14],[88,13],[59,3],[29,2]]
};
const months=[0,5,6,7,8,9,10,11,12,1,2,3,4,8,88,5,6];
export function thaiLunar(date){
 const m=/^(\d{4})-(\d{2})-(\d{2})$/.exec(date);if(!m)throw Error('Invalid date');
 const [year,month,day]=m.slice(1).map(Number);
 const dt=new Date(Date.UTC(year,month-1,day));if(dt.getUTCFullYear()!==year||dt.getUTCMonth()!==month-1||dt.getUTCDate()!==day)throw Error('Invalid date');
 // Gregorian JDN for dates after 1582-10-15.
 const a=Math.floor((14-month)/12),yy=year+4800-a,mm=month+12*a-3;
 const jd=day+Math.floor((153*mm+2)/5)+365*yy+Math.floor(yy/4)-Math.floor(yy/100)+Math.floor(yy/400)-32045;
 const hk=jd-1954167;if(hk<1)throw Error('Thai lunar date out of range');
 let cs=Math.floor((hk*800-373)/292207),days;
 if(mod(hk,292207)===95333){cs--;days=365;}else days=hk-lunarYear(cs).hk;
 let y=lunarYear(cs),yearDays=365+(y.leapday?1:0);
 while(days>yearDays){days-=yearDays;cs++;y=lunarYear(cs);yearDays=365+(y.leapday?1:0);}
 let n=y.offsetDays+days,monthL=5;
 for(const [boundary,idx] of boundaries[y.type])if(n>boundary){n-=boundary;monthL=months[idx];break;}
 return {side:n>15?'ข้างแรม':'ข้างขึ้น',day:n>15?n-15:n,month:monthL,csYear:cs};
}
