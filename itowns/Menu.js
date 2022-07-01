/* global dat */

/* eslint-disable no-underscore-dangle */
dat.GUI.prototype.removeFolder = function removeFolder(name) {
  const folder = this.__folders[name];
  if (!folder) return;
  folder.close();
  this.__ul.removeChild(folder.domElement.parentNode);
  delete this.__folders[name];
  this.onResize();
};
dat.GUI.prototype.hasFolder = function hasFolder(name) {
  return this.__folders[name];
};
/* eslint-enable no-underscore-dangle */

class Menu {
  constructor(menuDiv, view, shortCuts) {
    const width = 300;
    this.shortCuts = shortCuts;

    if (view) {
      this.gui = new dat.GUI({ autoPlace: false, width });
      menuDiv.appendChild(this.gui.domElement);

      this.colorGui = this.gui.addFolder('Color Layers');
      this.colorGui.open();
      this.vectorGui = this.gui.addFolder('Extra Layers [v]');
      this.vectorGui.domElement.id = 'extraLayers';
      this.vectorGui.open();
      this.view = view;

      view.addEventListener('layers-order-changed', ((ev) => {
        for (let i = 0; i < ev.new.sequence.length; i += 1) {
          const colorLayer = view.getLayerById(ev.new.sequence[i]);

          this.removeLayersGUI(colorLayer.id);
          this.addImageryLayerGUI(colorLayer);
        }
      }));
    }
  }

  addImageryLayerGUI(layer) {
    /* eslint-disable no-param-reassign */
    let typeGui = 'colorGui';
    if (!['Ortho', 'Opi', 'Graph', 'Contour', 'Patches'].includes(layer.id)) {
      typeGui = 'vectorGui';
    }
    if (this[typeGui].hasFolder(layer.id)) { return; }
    if (layer.id === 'selectedFeature') { return; }

    // name folder
    const folder = this[typeGui].addFolder(layer.id);
    if (this.shortCuts.visibleFolder[layer.id] !== undefined) {
      const titles = Array.from(folder.domElement.getElementsByClassName('title'));
      titles.forEach((title) => {
        if (title.innerText.startsWith(layer.id)) title.innerText += ` [${this.shortCuts.visibleFolder[layer.id]}]`;
      });
    }
    if (this.shortCuts.styleFolder[layer.id] !== undefined) {
      const titles = Array.from(folder.domElement.getElementsByClassName('title'));
      titles.forEach((title) => {
        if (title.innerText.startsWith(layer.id)) title.innerText += ` [${this.shortCuts.styleFolder[layer.id]}]`;
      });
    }

    // visibility
    const visib = folder.add({ visible: layer.visible }, 'visible');
    visib.domElement.setAttribute('id', layer.id);
    visib.domElement.classList.add('visibcbx');
    visib.onChange(((value) => {
      layer.visible = value;
      if (layer.isAlert === true) {
        this.view.getLayerById('selectedFeature').visible = value;
      }
      this.view.notifyChange(layer);
    }));

    // opacity
    folder.add({ opacity: layer.opacity }, 'opacity').min(0.001).max(1.0).onChange(((value) => {
      layer.opacity = value;
      this.view.notifyChange(layer);
    }));

    // style
    if (['Ortho', 'Opi'].includes(layer.id)) {
      const style = folder.add(layer.id === 'Ortho' ? this.view : this.view.Opi, 'style', this.view.styles);
      style.onChange((value) => {
        this.view.changeStyle(layer.id, value);
      });
    }

    // Patch pour ajouter la modification de l'epaisseur des contours dans le menu
    if (layer.effect_parameter) {
      folder.add({ thickness: layer.effect_parameter }, 'thickness').min(0.5).max(5.0).onChange(((value) => {
        layer.effect_parameter = value;
        this.view.notifyChange(layer);
      }));
    }

    // delete layer
    if (typeGui === 'vectorGui' && layer.id !== 'Remarques' && layer.isAlert === false) {
      folder.add(this.view, 'removeVectorLayer').name('delete').onChange(() => {
        // if (layer.isAlert === undefined) {
        this.view.removeVectorLayer(layer.id);
        this.removeLayersGUI(layer.id);
        // }
        // } else {
        //   // eslint-disable-next-line no-underscore-dangle
        //   this.gui.__controllers.filter((controller) => {
        //  // controller.property === 'message')[0].setValue('Couche en edition');
        //   // this.viewer.message = 'Couche en edition';
        // }
      });
    }
    /* eslint-enable no-param-reassign */
  }

  removeLayersGUI(nameLayer) {
    if (this.colorGui.hasFolder(nameLayer)) {
      this.colorGui.removeFolder(nameLayer);
    } else {
      this.vectorGui.removeFolder(nameLayer);
    }
  }
}

export default Menu;