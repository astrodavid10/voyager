import { createApp } from "vue";

import App from "./App.vue";
import { setAppHandle } from "./appHandle";
import { boolParam } from "./urlParams";
import "./assets/common.less";
import "./assets/voyager.less";

import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { library } from "@fortawesome/fontawesome-svg-core";
import {
  faChevronDown, faChevronLeft, faChevronRight, faChevronUp, faCircleInfo, faCompass, faHouse, faPause, faPlay, faShareNodes,
  faVolumeHigh, faXmark,
} from "@fortawesome/free-solid-svg-icons";
library.add(faChevronDown, faChevronLeft, faChevronRight, faChevronUp, faCircleInfo, faCompass, faHouse, faPause, faPlay, faShareNodes,
  faVolumeHigh, faXmark);

// iOS Safari: stop page-level pinch zoom; the 3D canvas handles its own pinch.
document.addEventListener("gesturestart", (e) => e.preventDefault(), { passive: false });

// NOTE: @wwtelescope/engine-pinia and three are NOT imported here. The light-day
// hook and the story card paint from this chunk alone; VoyagerView3D (async)
// installs the engine on this app when it loads (sol footgun 5 / AUDIT-UI #4).
const app = createApp(App, {
  kioskMode: boolParam("kiosk"),
  kioskHomeUrl: "https://astrodavid10.github.io/voyager/",
});
setAppHandle(app);
app.component("font-awesome-icon", FontAwesomeIcon).mount("#app");
