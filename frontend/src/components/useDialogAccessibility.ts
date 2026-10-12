import {useEffect} from "react";

// 不管理业务动作：只让现有 React modal 实现 Tab 焦点围栏、Escape 与打开前焦点归还。
// 采用身份检测，不在消息刷新时重复聚焦；禁用项和隐藏节点不加入键盘循环。
export function useDialogAccessibility(){
  useEffect(()=>{
    const root=document.getElementById("root");
    if(!root)return;
    let current:HTMLElement|null=null;
    let restore:HTMLElement|null=null;
    const focusables=()=>{
      if(!current)return [];
      return Array.from(current.querySelectorAll<HTMLElement>(
        'button:not([disabled]),a[href],input:not([disabled]),textarea:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])'
      )).filter(node=>node.getClientRects().length>0&&getComputedStyle(node).visibility!=="hidden");
    };
    const sync=()=>{
      const next=root.querySelector<HTMLElement>('[role="dialog"][aria-modal="true"]');
      if(current===next)return;
      if(next&&!current)restore=document.activeElement instanceof HTMLElement?document.activeElement:null;
      current=next;
      if(next){
        const focus=next.querySelector<HTMLElement>('input:not([disabled]),textarea:not([disabled]),[autofocus],button:not([disabled])');
        if(focus){queueMicrotask(()=>{if(current===next)focus.focus({preventScroll:true});});}
        else {next.tabIndex=-1;next.focus({preventScroll:true});}
      }else if(restore){const old=restore;restore=null;queueMicrotask(()=>old.isConnected&&old.focus({preventScroll:true}));}
    };
    const observer=new MutationObserver(sync);
    observer.observe(root,{childList:true,subtree:true});
    const onKeyDown=(event:KeyboardEvent)=>{
      if(!current)return;
      if(event.isComposing||event.keyCode===229)return;
      if(event.key==="Escape"){
        const close=current.querySelector<HTMLElement>('[data-dialog-close]');
        if(close){event.preventDefault();event.stopImmediatePropagation();close.click();}
        return;
      }
      if(event.key!=="Tab")return;
      const nodes=focusables();
      if(!nodes.length){event.preventDefault();current.focus();return;}
      const first=nodes[0],last=nodes.at(-1)!;
      if(event.shiftKey&&(document.activeElement===first||!current.contains(document.activeElement))){
        event.preventDefault();last.focus();
      }else if(!event.shiftKey&&(document.activeElement===last||!current.contains(document.activeElement))){
        event.preventDefault();first.focus();
      }
    };
    document.addEventListener("keydown",onKeyDown,true);
    sync();
    return ()=>{observer.disconnect();document.removeEventListener("keydown",onKeyDown,true);};
  },[]);
}
