(function(){
const tenant = document.currentScript.getAttribute('data-tenant');
const btn = document.createElement('button');
btn.textContent = '💬 Chat Betty';
btn.style.position='fixed'; btn.style.right='16px'; btn.style.bottom='16px'; btn.style.padding='10px 14px'; btn.style.borderRadius='24px'; btn.style.border='0'; btn.style.background='#111'; btn.style.color='#fff'; btn.style.cursor='pointer'; btn.style.zIndex='99999';
btn.onclick = () => {
window.open(`/t/${tenant}`, '_blank', 'width=420,height=640');
};
document.body.appendChild(btn);
})();