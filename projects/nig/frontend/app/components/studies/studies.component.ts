import { Component, Injector } from "@angular/core";
import { DataService } from "@app/services/data.service";
import { BasePaginationComponent } from "@rapydo/components/base.pagination.component";
import { Study } from "@app/types";

@Component({
  selector: "nig-studies",
  templateUrl: "./studies.component.html",
  styleUrls: ["./studies.component.css"],
})
export class StudiesComponent extends BasePaginationComponent<Study> {

	constructor(
		protected injector: Injector
	) {
		super(injector);
	    this.init("study", "study", "Studies");
	    this.initPaging(20, false);
	    this.list();
	}

}