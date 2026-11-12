<template>
  <aside v-if="ok" class="kqr" :class="{ big }" aria-label="Take it with you">
    <qrcode-vue :value="url" :size="big ? 200 : 96" level="M" render-as="svg" background="#ffffff" foreground="#05030f" />
    <p>{{ big ? "Take Voyager home: scan with your phone camera" : "Take it with you" }}</p>
  </aside>
</template>

<script lang="ts">
import { defineComponent } from "vue";
import QrcodeVue from "qrcode.vue";

import { isReachableFromPhone } from "../kiosk/takeHome";

export default defineComponent({
  name: "KioskQr",
  components: { "qrcode-vue": QrcodeVue },
  props: {
    url: { type: String, required: true },
    big: { type: Boolean, default: false },
  },
  computed: {
    ok(): boolean { return isReachableFromPhone(this.url); },
  },
});
</script>

<style lang="less">
.kqr {
  position: absolute; z-index: 7; right: 16px; top: 16px; padding: 10px; border-radius: 14px;
  background: #fff; color: #05030f; text-align: center; transition: transform 400ms ease;
  svg { display: block; }
  p { margin: 6px 0 0; font-size: 13px; font-weight: 700; max-width: 120px; line-height: 1.2; }
  &.big { right: auto; left: 50%; top: 50%; transform: translate(-50%, -50%); padding: 18px;
    p { font-size: 18px; max-width: 220px; } }
}
</style>
