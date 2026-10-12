import {useQuery, useQueryClient} from "@tanstack/react-query";
import {useSyncExternalStore} from "react";
import {workspace} from "./api";
import {activeStatus} from "./types";

function subscribeRoute(callback:()=>void) {
  window.addEventListener("hashchange",callback);
  return ()=>window.removeEventListener("hashchange",callback);
}
function routeSnapshot(){return window.location.hash.slice(1)||"chat";}
function serverSnapshot(){return "chat";}
export function useRoute(){
  const hash=useSyncExternalStore(subscribeRoute,routeSnapshot,serverSnapshot);
  const [name,id]=hash.split("/");
  const page=["chat","sessions","projects","knowledge","goals","runtime","settings"].includes(name)?name:"chat";
  return {page,id:id||null};
}
export function navigate(page:string,id?:string) {
  window.location.hash=page+(id?"/"+encodeURIComponent(id):"");
}
export function useBootstrap(){
  return useQuery({
    queryKey:["workspace","bootstrap"],
    queryFn:({signal})=>workspace.bootstrap(signal),
    refetchInterval:12000,
    retry:1
  });
}
export function useSession(id:string|null) {
  return useQuery({
    queryKey:["workspace","session",id],
    queryFn:({signal})=>workspace.session(id!,signal),
    enabled:!!id,
    refetchInterval:(q)=>{
      const turn=q.state.data?.turns.at(-1);
      return turn && activeStatus.has(turn.status)?1200:4800;
    },
    retry:1
  });
}
export function useRefresh() {
  const client=useQueryClient();
  return async (id?:string|null)=>{
    await Promise.all([
      client.invalidateQueries({queryKey:["workspace","bootstrap"]}),
      ...(id?[client.invalidateQueries({queryKey:["workspace","session",id]})]:[]),
    ]);
  };
}
