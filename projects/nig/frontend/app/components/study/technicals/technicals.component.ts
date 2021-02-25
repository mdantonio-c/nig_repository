import { Component, Injector, Input } from "@angular/core";
import { DataService } from "@app/services/data.service";
import { BasePaginationComponent } from "@rapydo/components/base.pagination.component";
import { TechnicalMetadata } from "@app/types";

@Component({
  selector: "nig-technicals",
  templateUrl: "./technicals.component.html"
})
export class TechnicalsComponent extends BasePaginationComponent<TechnicalMetadata> {
	@Input() studyUUID;

	constructor(
		protected injector: Injector
	) {
		super(injector);
	}

	ngOnInit() {
		this.init("technicals", `study/${this.studyUUID}/technicals`, "Technicals");
	    this.initPaging(20, false);
	    this.list();
	}

}