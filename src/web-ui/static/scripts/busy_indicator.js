/* busy_indicator | busy_indicator 0.10.0 | License - GNU LGPL 3 */
/*
  This library is free software: you can redistribute it and/or modify
  it under the terms of the GNU Lesser General Public License as published by
  the Free Software Foundation, either version 3 of the License, or
  (at your option) any later version.

  This program is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
  GNU Lesser General Public License for more details.

  You should have received a copy of the GNU Lesser General Public License
  along with this program.  If not, see <http://www.gnu.org/licenses/>.

  https://github.com/lego12239/busy_indicator.js
*/

"use strict";

function busy_indicator(cntr_el, img_el, show_cb, hide_cb)
{
	this.el = {};
	this.cb = {show: null, hide: null};
	this.pos = {x: 0, y: 0};
	this.show_class = "show";


	this._set_prm.call(this.el, "cntr", cntr_el);
	this.el.img = img_el;
	if (show_cb != undefined)
		this.cb.show = show_cb;
	if (hide_cb != undefined)
		this.cb.hide = hide_cb;

	this.cnt = 0;
}

busy_indicator.prototype._set_prm = function (n, v)
{
	if (( v == undefined ) || ( v == null ))
		throw("busy_indicator: " + n + " is not supplied");
	this[n] = v;
}

busy_indicator.prototype.show = function ()
{
	var top, left;
	var img_el;


	this.cnt++;
	if ( this.cnt > 1 )
		return;

	this.el.cntr.classList.add(this.show_class);

	this.align();
	
	if (this.cb.show != undefined)
		this.cb.show();
}

busy_indicator.prototype.align = function ()
{
	if (this.el.img == null)
		return;
	
	this.pos = this.calc_pos();

	this.el.img.style.top = this.pos.y + "px";
	this.el.img.style.left = this.pos.x + "px";
}

busy_indicator.prototype.calc_pos = function ()
{
	var x, y;


	x = this.el.cntr.clientWidth/2 - this.el.img.offsetWidth/2;
	y = this.el.cntr.clientHeight/2 - this.el.img.offsetHeight/2;
	
	return {x: x, y: y};
}

busy_indicator.prototype.hide = function ()
{
	if ( this.cnt > 0 )
		this.cnt--;
	else
		return;

	if ( this.cnt )
		return;

	this.el.cntr.classList.remove(this.show_class);

	if (this.cb.hide != undefined)
		this.cb.hide();
}
